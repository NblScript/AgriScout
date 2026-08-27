"""大屏聚合统计 /stats/overview 测试：计数/建议分布/近几次巡检摘要。"""
import base64
import io

from PIL import Image

BASE = "/api/v1"
SOWING = "2026-08-01"


def _png_b64(rgb: tuple[int, int, int]) -> str:
    img = Image.new("RGB", (24, 24), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


BROWN = _png_b64((120, 85, 50))
GREEN = _png_b64((40, 160, 60))


def _seed_and_upload(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={
            "name": "统计测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-d01", "name": "统计测试车", "type": "rover"})
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
    # 一条无条件常规规则 → 上传后建议阶段必产出，便于断言建议分布
    resp = client.post(
        f"{BASE}/rules",
        json={
            "rule_key": "R-STATS-ROUTINE",
            "tier": "routine",
            "priority": "low",
            "condition": {},
            "action": "常规巡检保底建议。",
            "source": "测试",
        },
    )
    assert resp.status_code == 201, resp.text

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


def test_overview_empty_db(client):
    s = client.get(f"{BASE}/stats/overview").json()
    assert s["fields"] == 0 and s["patrols"] == 0
    assert s["advices_total"] == 0
    assert s["recent_patrols"] == []


def test_overview_aggregates_after_patrol(client):
    patrol_id = _seed_and_upload(client)

    # 人工标注一条，计入手动复核数
    point_id = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"][0]["id"]
    ann = client.post(
        f"{BASE}/capture-points/{point_id}/annotations",
        json={"label": "dry_stress", "annotator_name": "统计员"},
    )
    assert ann.status_code == 201, ann.text

    s = client.get(f"{BASE}/stats/overview").json()

    # 资源计数
    assert s["fields"] == 1
    assert s["crops"] == 1
    assert s["plantings"] == 1
    assert s["devices"] == 1
    assert s["patrols"] == 1
    assert s["capture_points"] == 2
    assert s["analyzed_points"] == 2
    assert s["annotations"] == 1

    # 建议分布：两点各一条常规保底
    assert s["advices_total"] >= 2
    assert s["advices_suggested"] == s["advices_total"]

    # 近几次巡检摘要
    assert len(s["recent_patrols"]) == 1
    rp = s["recent_patrols"][0]
    assert rp["patrol_id"] == patrol_id
    assert rp["field_name"] == "统计测试田"
    assert rp["point_count"] == 2
    assert rp["analyzed_points"] == 2
    assert rp["avg_ndvi"] is not None
    assert sum(rp["vigor_distribution"].values()) == 2
    assert all(k in {"1", "2", "3", "4", "5"} for k in rp["vigor_distribution"])

    # 采纳一条建议后分布变化
    advices = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["items"]
    client.patch(f"{BASE}/advices/{advices[0]['id']}", json={"status": "accepted"})
    s2 = client.get(f"{BASE}/stats/overview").json()
    assert s2["advices_accepted"] == 1
    assert s2["advices_suggested"] == s2["advices_total"] - 1
