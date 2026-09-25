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


def _prediction(client, *, forecast_hours=48, captured_at: str | None = None):
    """captured_at 缺省用 _package 的固定历史时间（窗口早已结束）；传当前时间可得到未结束的窗口。"""
    field_id = _setup(client)
    package = _package(field_id)
    if captured_at is not None:
        package["patrol"]["started_at"] = captured_at
        package["patrol"].pop("ended_at")
        for point in package["capture_points"]:
            point["captured_at"] = captured_at
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=package).json()["patrol_id"]
    preds = client.post(
        f"{BASE}/patrols/{patrol_id}/risk-predictions/generate",
        json={"target_event": "目标病害首次显症", "forecast_hours": forecast_hours},
    ).json()
    return field_id, preds[0]


EVIDENCE = {"reference": "/media/recheck-001.jpg"}


def test_negative_follow_up_requires_window_to_have_ended(client):
    """申报书 8.2：阴性需完成规定窗口的复查——窗口没走完就记阴性会污染评估标签。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    _, open_window = _prediction(client, forecast_hours=48, captured_at=now)  # 窗口刚开始
    early = client.post(f"{BASE}/risk-predictions/{open_window['id']}/follow-up", json={
        "status": "confirmed_negative", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "未见症状",
    })
    assert early.status_code == 422 and "窗口" in early.json()["detail"]
    # 窗口内可以先记 insufficient，之后再补结论
    pending = client.post(f"{BASE}/risk-predictions/{open_window['id']}/follow-up", json={
        "status": "insufficient", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "遮挡",
    })
    assert pending.status_code == 200


def test_negative_follow_up_after_window_is_accepted(client):
    _, closed_window = _prediction(client, forecast_hours=48)  # 2026-09-20 起 48h，已结束
    resp = client.post(f"{BASE}/risk-predictions/{closed_window['id']}/follow-up", json={
        "status": "confirmed_negative", "reviewed_by": "农技员", "evidence": EVIDENCE,
        "note": "窗口内复查未发病", "event_confirmed": False,
    })
    assert resp.status_code == 200


def test_positive_follow_up_event_time_must_fall_in_window(client):
    _, pred = _prediction(client, forecast_hours=48)
    body = {"status": "confirmed_positive", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "显症"}
    after = client.post(f"{BASE}/risk-predictions/{pred['id']}/follow-up",
                        json={**body, "event_at": "2026-09-30T08:00:00+00:00"})
    assert after.status_code == 422
    before = client.post(f"{BASE}/risk-predictions/{pred['id']}/follow-up",
                         json={**body, "event_at": "2026-09-19T08:00:00+00:00"})
    assert before.status_code == 422
    contradict = client.post(f"{BASE}/risk-predictions/{pred['id']}/follow-up",
                             json={**body, "event_confirmed": False})
    assert contradict.status_code == 422
    inside = client.post(f"{BASE}/risk-predictions/{pred['id']}/follow-up",
                         json={**body, "event_at": "2026-09-21T08:00:00+08:00", "event_confirmed": True})
    assert inside.status_code == 200


def test_manual_prediction_with_mixed_timezones_does_not_500(client):
    field_id = _setup(client)
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=_package(field_id)).json()["patrol_id"]
    resp = client.post(f"{BASE}/risk-predictions", json={
        "patrol_id": patrol_id, "observation_key": "manual", "target_event": "x",
        "forecast_hours": 24, "forecast_start": "2026-09-20T08:00:00+08:00",
        "forecast_end": "2026-09-21T00:00:00",  # 无时区按 UTC：恰好 24h
        "probability": 0.5, "level": "medium", "confidence": 0.5, "model_version": "m",
    })
    assert resp.status_code == 201, resp.text


def test_revisit_task_patch_null_status_is_422(client):
    field_id = _setup(client)
    task = client.post(f"{BASE}/revisit-tasks", json={
        "field_id": field_id, "task_type": "revisit", "priority": 0.5, "value_score": 0.5,
    }).json()
    assert client.patch(f"{BASE}/revisit-tasks/{task['id']}", json={"status": None}).status_code == 422


def _season_package(field_id: int, day: str, photos: list[str]):
    """同一地块、同一组坐标、不同日期的巡检（模拟多日期复巡）。"""
    return {
        "patrol": {"field_id": field_id, "device": "loop-01", "started_at": f"{day}T08:00:00+00:00"},
        "capture_points": [
            {"seq": i, "distance_m": i * 0.5, "lng": 10.00001, "lat": 10.00001 + i * 0.5 / 111_320,
             "captured_at": f"{day}T08:0{i}:00+00:00", "photo": photo,
             "weather": {"temp_c": 20, "humidity_pct": 90, "rain_mm": 3}}
            for i, photo in enumerate(photos)
        ],
    }


def test_risk_generation_uses_region_history_across_patrols(client):
    """同一观察区域的历史巡检进入预测：趋势不再恒为 unknown（审查第 19 项）。"""
    field_id = _setup(client)
    green, brown = png_b64((40, 160, 60)), png_b64((120, 85, 50))
    first = client.post(f"{BASE}/ingest/patrol", json=_season_package(field_id, "2026-09-01", [green, green])).json()
    second = client.post(f"{BASE}/ingest/patrol", json=_season_package(field_id, "2026-09-04", [brown, green])).json()

    body = {"target_event": "首次显症", "forecast_hours": 72}
    old = client.post(f"{BASE}/patrols/{first['patrol_id']}/risk-predictions/generate", json=body).json()
    new = client.post(f"{BASE}/patrols/{second['patrol_id']}/risk-predictions/generate", json=body).json()

    assert {p["observation_key"] for p in old} == {p["observation_key"] for p in new}  # 同一区域
    assert all(p["observation_key"].startswith(f"field-{field_id}/grid2.5m/") for p in new)
    assert all(p["model_version"] == "risk-heuristic-v2" for p in new)
    region = new[0]["evidence"]["region"]
    assert region["history_patrol_ids"] == [first["patrol_id"]]
    assert region["region_risk_score"] > region["history_risk_scores"][0]  # 区域取最大值：一个病点即可反映
    assert new[0]["trend"] == "rising" and old[0]["trend"] == "unknown"
    assert new[0]["probability"] > old[0]["probability"]


def test_history_never_uses_future_patrols(client):
    field_id = _setup(client)
    green, brown = png_b64((40, 160, 60)), png_b64((120, 85, 50))
    early = client.post(f"{BASE}/ingest/patrol", json=_season_package(field_id, "2026-09-01", [green])).json()
    client.post(f"{BASE}/ingest/patrol", json=_season_package(field_id, "2026-09-05", [brown]))
    preds = client.post(f"{BASE}/patrols/{early['patrol_id']}/risk-predictions/generate",
                        json={"target_event": "首次显症"}).json()
    assert preds[0]["evidence"]["region"]["history_patrol_ids"] == []


def test_metrics_endpoint_scores_follow_ups_with_status_semantics(client):
    field_id = _setup(client)
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=_package(field_id)).json()["patrol_id"]
    preds = client.post(f"{BASE}/patrols/{patrol_id}/risk-predictions/generate",
                        json={"target_event": "首次显症", "forecast_hours": 48}).json()
    assert len(preds) == 2
    low, high = sorted(preds, key=lambda p: p["probability"])
    client.post(f"{BASE}/risk-predictions/{high['id']}/follow-up", json={
        "status": "confirmed_positive", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "显症",
        "event_at": "2026-09-21T08:00:00+00:00",
    })
    client.post(f"{BASE}/risk-predictions/{low['id']}/follow-up", json={
        "status": "confirmed_negative", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "未发病",
    })
    resp = client.get(f"{BASE}/risk-predictions/metrics", params={
        "target_event": "首次显症", "model_version": "risk-heuristic-v2", "lead_threshold": 0.0,
    })
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["evaluable"] == 2 and report["positives"] == 1
    assert report["pr_auc"] == 1.0  # 高分的是阳性
    assert report["lead_time"]["events"] == 1 and report["lead_time"]["warned"] == 1
    assert report["lead_time"]["median_lead_hours"] > 0
    # 其他模型版本不混在一起评估
    other = client.get(f"{BASE}/risk-predictions/metrics",
                       params={"target_event": "首次显症", "model_version": "risk-heuristic-v1"}).json()
    assert other["evaluable"] == 0 and other["scope"]["predictions"] == 0


def test_lead_time_defaults_to_fixed_false_alarm_threshold(client):
    """提前量缺省在「相同误报负担」下计算：阈值取 recall_at_fp 的阈值，而不是固定 0.5。"""
    field_id = _setup(client)
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=_package(field_id)).json()["patrol_id"]
    preds = client.post(f"{BASE}/patrols/{patrol_id}/risk-predictions/generate",
                        json={"target_event": "首次显症", "forecast_hours": 48}).json()
    low, high = sorted(preds, key=lambda p: p["probability"])
    client.post(f"{BASE}/risk-predictions/{high['id']}/follow-up", json={
        "status": "confirmed_positive", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "显症",
        "event_at": "2026-09-21T08:00:00+00:00",
    })
    client.post(f"{BASE}/risk-predictions/{low['id']}/follow-up", json={
        "status": "confirmed_negative", "reviewed_by": "农技员", "evidence": EVIDENCE, "note": "未发病",
    })
    report = client.get(f"{BASE}/risk-predictions/metrics", params={
        "target_event": "首次显症", "model_version": "risk-heuristic-v2", "fp_per_unit": 0,
    }).json()
    lead = report["lead_time"]
    assert lead["threshold"] == report["recall_at_fp"]["threshold"] == high["probability"]
    assert "误报" in lead["threshold_source"] and lead["warned"] == 1
