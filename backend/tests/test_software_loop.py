"""M7 软件闭环 API：风险预测、主动任务、随访和模型发布闸门。"""
from conftest import png_b64

BASE = "/api/v1"


def _setup(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={"name": "闭环测试田", "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]] }},
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "loop-01", "name": "闭环小车", "type": "rover"})
    return field_id


def _package(field_id: int):
    return {
        "patrol": {
            "field_id": field_id, "device": "loop-01",
            "started_at": "2026-09-20T08:00:00+00:00", "ended_at": "2026-09-20T08:10:00+00:00",
        },
        "capture_points": [
            {"seq": 0, "distance_m": 0.0, "lng": 10.001, "lat": 10.001,
             "captured_at": "2026-09-20T08:00:00+00:00", "photo": png_b64((40, 160, 60)),
             "weather": {"temp_c": 25, "humidity_pct": 80, "rain_mm": 2}},
            {"seq": 1, "distance_m": 0.5, "lng": 10.002, "lat": 10.001,
             "captured_at": "2026-09-20T08:01:00+00:00", "photo": png_b64((120, 85, 50)),
             "weather": {"temp_c": 25, "humidity_pct": 85, "rain_mm": 4}},
        ],
    }


def test_software_loop_end_to_end(client):
    field_id = _setup(client)
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=_package(field_id)).json()["patrol_id"]

    generated = client.post(
        f"{BASE}/patrols/{patrol_id}/risk-predictions/generate",
        json={"target_event": "目标病害首次显症", "forecast_hours": 48},
    )
    assert generated.status_code == 200
    predictions = generated.json()
    assert len(predictions) == 2
    prediction_id = predictions[-1]["id"]
    assert predictions[-1]["evidence"]["prediction_evidence"]

    incomplete = client.post(
        f"{BASE}/risk-predictions/{prediction_id}/follow-up",
        json={"status": "confirmed_negative", "reviewed_by": "农技员"},
    )
    assert incomplete.status_code == 422

    follow = client.post(
        f"{BASE}/risk-predictions/{prediction_id}/follow-up",
        json={"status": "confirmed_positive", "reviewed_by": "农技员", "event_confirmed": True,
              "evidence": {"reference": "/media/recheck-point-1.jpg"}},
    )
    assert follow.status_code == 200
    assert follow.json()["status"] == "confirmed_positive"

    tasks = client.post(
        f"{BASE}/revisit-tasks/generate",
        json={"field_id": field_id, "patrol_id": patrol_id, "limit": 10},
    )
    assert tasks.status_code == 200
    assert tasks.json() and tasks.json()[0]["task_type"] in {"revisit", "label", "random"}
    assigned = client.patch(
        f"{BASE}/revisit-tasks/{tasks.json()[0]['id']}",
        json={"status": "assigned"},
    )
    assert assigned.status_code == 200 and assigned.json()["status"] == "assigned"
    running = client.patch(
        f"{BASE}/revisit-tasks/{tasks.json()[0]['id']}", json={"status": "running"},
    )
    assert running.status_code == 200 and running.json()["status"] == "running"
    completed = client.patch(
        f"{BASE}/revisit-tasks/{tasks.json()[0]['id']}",
        json={"status": "completed", "result_note": "已完成复巡"},
    )
    assert completed.status_code == 200 and completed.json()["status"] == "completed"

    points = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}&limit=10").json()["items"]
    annotation = client.post(
        f"{BASE}/capture-points/{points[0]['id']}/annotations",
        json={"label": "suspected_disease", "annotator_name": "农技员", "note": "复核"},
    )
    assert annotation.status_code == 201

    dataset = client.post(
        f"{BASE}/datasets/versions",
        json={"name": "wheat-field", "version": "v1", "row_count": 2,
              "label_schema": {"target": "disease"}},
    ).json()
    frozen = client.post(
        f"{BASE}/datasets/versions/{dataset['id']}/freeze", json={"row_count": 2},
    )
    assert frozen.status_code == 200 and frozen.json()["status"] == "frozen"
    assert frozen.json()["row_count"] == 1 and frozen.json()["snapshot_sha256"]

    evaluation = client.post(
        f"{BASE}/model-evaluations",
        json={"dataset_version_id": dataset["id"], "model_name": "risk", "model_version": "v1",
              "split": "test", "metrics": {"pr_auc": 0.71}, "evaluated_at": "2026-09-20T10:00:00+00:00"},
    ).json()
    approved = client.post(
        f"{BASE}/model-evaluations/{evaluation['id']}/approve", json={"approved_by": "负责人"},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
