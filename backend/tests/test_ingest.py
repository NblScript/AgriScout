"""M2 数据接入测试：巡检包上传 → 查询回读全链路。"""
import base64

# 1x1 红色 PNG（真实图片字节，用于魔数判型与落盘验证）
TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

BASE = "/api/v1"


def _setup_field_and_device(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={
            "name": "接入测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    ).json()["id"]
    device_code = "sim-t01"
    client.post(f"{BASE}/devices", json={"code": device_code, "name": "测试小车", "type": "rover"})
    return field_id, device_code


def _package(field_id: int, device: str, *, points=3, photo=None):
    return {
        "patrol": {
            "field_id": field_id,
            "device": device,
            "started_at": "2026-08-26T08:00:00+00:00",
            "ended_at": "2026-08-26T09:30:00+00:00",
            "track": [[10.001, 10.001], [10.002, 10.002], [10.003, 10.003]],
        },
        "capture_points": [
            {
                "seq": i,
                "distance_m": round(i * 0.5, 1),
                "lng": 10.001 + i * 0.001,
                "lat": 10.001 + i * 0.001,
                "captured_at": f"2026-08-26T08:{i:02d}:00+00:00",
                "photo": photo(i) if callable(photo) else photo,
                "weather": {
                    "temp_c": 26.5 + i,
                    "humidity_pct": 60 + i,
                    "light_lux": 40000 + i * 100,
                    "wind_mps": 1.2,
                    "rain_mm": 0.0,
                    "soil_moisture_pct": 33.3,
                },
            }
            for i in range(points)
        ],
    }


def _ingest(client, payload):
    return client.post(f"{BASE}/ingest/patrol", json=payload)


def test_ingest_roundtrip_with_photos(client, media_dir):
    field_id, device = _setup_field_and_device(client)
    pkg = _package(field_id, device, points=2, photo=lambda i: TINY_PNG if i == 0 else "/media/external-ref.jpg")
    resp = _ingest(client, pkg)
    assert resp.status_code == 201
    body = resp.json()
    assert body["capture_points"] == 2
    assert body["photos_saved"] == 1          # PNG 落盘
    assert body["photos_referenced"] == 1     # URL 引用透传

    # 详情：轨迹已转 LineString，点数正确
    detail = client.get(f"{BASE}/patrols/{body['patrol_id']}").json()
    assert detail["track"]["type"] == "LineString"
    assert len(detail["track"]["coordinates"]) == 3
    assert detail["point_count"] == 2
    assert detail["status"] == "received" and detail["analysis_status"] == "pending"
    assert detail["device_code"] == device

    # 采样点回读：坐标/天气完整
    points = client.get(f"{BASE}/capture-points?patrol_id={body['patrol_id']}").json()
    assert points["total"] == 2
    first = points["items"][0]
    assert first["lng"] == 10.001 and first["distance_m"] == 0.0
    assert first["weather"]["temp_c"] == 26.5 and first["weather"]["soil_moisture_pct"] == 33.3
    assert first["photo_url"].startswith("/media/") and first["photo_url"].endswith(".png")

    # 巡检列表过滤
    listed = client.get(f"{BASE}/patrols?field_id={field_id}&status=received").json()
    assert listed["total"] == 1

    # 照片按内容寻址落盘且字节完整（PNG 魔数）
    saved = media_dir / first["photo_url"].removeprefix("/media/")
    assert saved.exists()
    assert saved.read_bytes()[:4] == b"\x89PNG"


def test_bbox_query(client):
    field_id, device = _setup_field_and_device(client)
    resp = _ingest(client, _package(field_id, device))
    patrol_id = resp.json()["patrol_id"]

    # 命中区间
    hit = client.get(f"{BASE}/capture-points?bbox=10.000,10.000,10.0025,10.0025").json()
    assert hit["total"] == 2
    assert all(10.0 <= it["lng"] <= 10.0025 for it in hit["items"])

    # 空区间 & patrol_id 组合过滤
    miss = client.get(f"{BASE}/capture-points?bbox=-1,-1,0,0&patrol_id={patrol_id}").json()
    assert miss["total"] == 0

    # 非法 bbox → 422
    assert client.get(f"{BASE}/capture-points?bbox=1,2,3").status_code == 422
    assert client.get(f"{BASE}/capture-points?bbox=a,b,c,d").status_code == 422


def test_pagination(client):
    field_id, device = _setup_field_and_device(client)
    _ingest(client, _package(field_id, device, points=5))

    page1 = client.get(f"{BASE}/capture-points?limit=2").json()
    assert page1["total"] == 5 and [it["seq"] for it in page1["items"]] == [0, 1]
    page3 = client.get(f"{BASE}/capture-points?limit=2&skip=4").json()
    assert [it["seq"] for it in page3["items"]] == [4]


def test_duplicate_package_rejected(client):
    field_id, device = _setup_field_and_device(client)
    pkg = _package(field_id, device)
    assert _ingest(client, pkg).status_code == 201
    dup = _ingest(client, pkg)
    assert dup.status_code == 409
    assert "重复上传" in dup.json()["detail"]


def test_unknown_field_or_device_404(client):
    client.post(f"{BASE}/devices", json={"code": "known-01", "name": "已知设备", "type": "rover"})
    bad_field = _package(9999, "known-01")
    assert _ingest(client, bad_field).status_code == 404

    field_id, _ = _setup_field_and_device(client)
    bad_device = _package(field_id, "ghost-99")
    assert _ingest(client, bad_device).status_code == 404
    assert "未登记" in _ingest(client, bad_device).json()["detail"]


def test_protocol_validation_errors(client):
    field_id, device = _setup_field_and_device(client)

    # 空 capture_points
    empty = _package(field_id, device)
    empty["capture_points"] = []
    assert _ingest(client, empty).status_code == 422

    # 重复 seq
    dup_seq = _package(field_id, device)
    dup_seq["capture_points"][1]["seq"] = 0
    assert _ingest(client, dup_seq).status_code == 422

    # 非法 base64 照片
    bad_photo = _package(field_id, device, points=1, photo="@@not-base64@@")
    assert _ingest(client, bad_photo).status_code == 422

    # 时间倒流
    time_travel = _package(field_id, device)
    time_travel["patrol"]["ended_at"] = "2026-08-26T07:00:00+00:00"
    assert _ingest(client, time_travel).status_code == 422

    # track 三元组
    bad_track = _package(field_id, device)
    bad_track["patrol"]["track"] = [[1, 2, 3]]
    assert _ingest(client, bad_track).status_code == 422

    # 天气越界（湿度 120%）
    bad_weather = _package(field_id, device, points=1)
    bad_weather["capture_points"][0]["weather"]["humidity_pct"] = 120
    assert _ingest(client, bad_weather).status_code == 422


def test_base64_data_uri_accepted(client):
    field_id, device = _setup_field_and_device(client)
    data_uri = f"data:image/png;base64,{TINY_PNG}"
    resp = _ingest(client, _package(field_id, device, points=1, photo=data_uri))
    assert resp.status_code == 201 and resp.json()["photos_saved"] == 1
