"""M6+ 标注回流测试：复核落库/幂等 upsert/进度汇总/NDJSON 数据集导出。"""
import json

from conftest import png_b64

BASE = "/api/v1"
SOWING = "2026-08-01"


BROWN = png_b64((120, 85, 50))  # 枯黄胁迫点
GREEN = png_b64((40, 160, 60))  # 正常植被点


def _setup_and_upload(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={
            "name": "标注测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-d01", "name": "标注测试车", "type": "rover"})
    crop_id = client.post(
        f"{BASE}/crops",
        json={
            "name": "冬小麦",
            "lifecycle_days": 60,
            "stages": [
                {"name": "出苗期", "days": 15},
                {"name": "分蘖期", "days": 30},
                {"name": "拔节期", "days": 15},
            ],
        },
    ).json()["id"]
    client.post(
        f"{BASE}/plantings", json={"field_id": field_id, "crop_id": crop_id, "sowing_date": SOWING}
    )
    pkg = {
        "patrol": {
            "field_id": field_id,
            "device": "sim-d01",
            "started_at": "2026-09-20T08:00:00+00:00",
            "ended_at": "2026-09-20T09:00:00+00:00",
        },
        "capture_points": [
            {"seq": 0, "distance_m": 0.0, "lng": 10.001, "lat": 10.0,
             "captured_at": "2026-09-20T08:00:00+00:00", "photo": BROWN,
             "weather": {"temp_c": 25, "soil_moisture_pct": 40}},
            {"seq": 1, "distance_m": 0.5, "lng": 10.002, "lat": 10.0,
             "captured_at": "2026-09-20T08:05:00+00:00", "photo": GREEN,
             "weather": {"temp_c": 25, "soil_moisture_pct": 70}},
        ],
    }
    resp = client.post(f"{BASE}/ingest/patrol", json=pkg)
    assert resp.status_code == 201, resp.text
    return resp.json()["patrol_id"]


def _points(client, patrol_id):
    return client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"]


def test_annotation_flow_upsert_patch_delete(client):
    patrol_id = _setup_and_upload(client)
    points = _points(client, patrol_id)
    assert len(points) == 2
    dry_point = next(p for p in points if p["seq"] == 0)

    # 创建 → 201；photo 已入库可导出
    resp = client.post(
        f"{BASE}/capture-points/{dry_point['id']}/annotations",
        json={"label": "suspected_disease", "annotator_name": "张三", "note": "叶缘发黄"},
    )
    assert resp.status_code == 201, resp.text
    ann = resp.json()
    assert ann["patrol_id"] == patrol_id
    assert ann["bbox"] is None  # bbox 预留字段，当前恒空

    # 同点同标签再提交 → 200 更新而非插重（幂等 upsert）
    again = client.post(
        f"{BASE}/capture-points/{dry_point['id']}/annotations",
        json={"label": "suspected_disease", "annotator_name": "李四", "note": "复核确认病害"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["id"] == ann["id"]
    assert again.json()["annotator_name"] == "李四"

    # 同点不同标签 → 新增一条
    normal = client.post(
        f"{BASE}/capture-points/{dry_point['id']}/annotations",
        json={"label": "normal", "annotator_name": "张三"},
    )
    assert normal.status_code == 201

    listed = client.get(f"{BASE}/capture-points/{dry_point['id']}/annotations").json()
    assert {a["label"] for a in listed} == {"suspected_disease", "normal"}

    # 改成同点已存在的标签 → 409；改备注 → 200
    clash = client.patch(f"{BASE}/annotations/{normal.json()['id']}", json={"label": "suspected_disease"})
    assert clash.status_code == 409
    patched = client.patch(f"{BASE}/annotations/{normal.json()['id']}", json={"note": "误标修正"})
    assert patched.status_code == 200 and patched.json()["note"] == "误标修正"

    # 非法标签 / 不存在的点与标注 → 422/404
    assert client.post(
        f"{BASE}/capture-points/{dry_point['id']}/annotations",
        json={"label": "foo", "annotator_name": "x"},
    ).status_code == 422
    assert client.post(
        f"{BASE}/capture-points/99999/annotations", json={"label": "normal", "annotator_name": "x"}
    ).status_code == 404
    assert client.delete(f"{BASE}/annotations/99999").status_code == 404

    # 汇总进度：两个点，1 个点被复核过（两类标签），共 2 条标注
    summary = client.get(f"{BASE}/patrols/{patrol_id}/annotations/summary").json()
    assert summary["points_total"] == 2
    assert summary["annotated_points"] == 1
    assert summary["annotations_total"] == 2

    # 巡检维度分页列表按标签过滤
    only_dry = client.get(f"{BASE}/patrols/{patrol_id}/annotations?label=suspected_disease").json()
    assert only_dry["total"] == 1 and only_dry["items"][0]["label"] == "suspected_disease"

    # 删除后汇总同步减少
    assert client.delete(f"{BASE}/annotations/{normal.json()['id']}").status_code == 204
    after = client.get(f"{BASE}/patrols/{patrol_id}/annotations/summary").json()
    assert after["annotated_points"] == 1 and after["annotations_total"] == 1


def test_export_dataset_ndjson_with_machine_prediction(client):
    """导出行含人工标签 + 照片 + 机器分析快照（人机分歧可直接比对）。"""
    patrol_id = _setup_and_upload(client)
    points = _points(client, patrol_id)
    for p, label in zip(sorted(points, key=lambda x: x["seq"]), ["suspected_disease", "normal"]):
        resp = client.post(
            f"{BASE}/capture-points/{p['id']}/annotations",
            json={"label": label, "annotator_name": "验收员"},
        )
        assert resp.status_code == 201, resp.text

    resp = client.get(f"{BASE}/annotations/export?patrol_id={patrol_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in resp.headers["content-disposition"]

    lines = [json.loads(line) for line in resp.text.splitlines()]
    assert len(lines) == 2
    by_label = {row["label"]: row for row in lines}

    suspect = by_label["suspected_disease"]
    assert suspect["photo_url"] and suspect["photo_url"].startswith("/media/")
    assert suspect["point"]["seq"] == 0 and suspect["point"]["lng"] == 10.001
    assert suspect["bbox"] is None
    # 后台分析在 TestClient 中已同步跑完，机器结论应随行携带
    assert suspect["analysis"] is not None
    assert suspect["analysis"]["analyzer_version"]
    assert suspect["reviewed_at"]

    # 全量导出（不带巡检过滤）行数一致
    all_rows = [json.loads(x) for x in client.get(f"{BASE}/annotations/export").text.splitlines()]
    assert len(all_rows) == len(lines)


def test_export_empty_is_valid_ndjson(client):
    """无标注时导出为空文件而非报错。"""
    patrol_id = _setup_and_upload(client)
    resp = client.get(f"{BASE}/annotations/export?patrol_id={patrol_id}")
    assert resp.status_code == 200
    assert resp.text == ""
