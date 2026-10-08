"""计划 0016 阶段 B1：照片分步上传接口、按 SHA-256 查重、巡检包 /media/ 引用校验，以及手写 v2 示例包。"""
import base64
import copy
import hashlib
import io

from PIL import Image

from app.schemas import patrol as patrol_schema
from test_auth import _add_user, _headers

BASE = "/api/v1"
BOUNDARY = {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10.001], [10, 10]]]}


def _image(rgb, fmt="JPEG", size=(32, 24)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format=fmt)
    return buf.getvalue()


def _upload(client, data: bytes, content_type="image/jpeg", headers=None):
    return client.post(f"{BASE}/media", content=data, headers={"Content-Type": content_type, **(headers or {})})


def _setup(client, headers=None):
    field_id = client.post(f"{BASE}/fields", json={"name": "分步上传田", "boundary": BOUNDARY,
                                                   "facility_type": "plastic_tunnel"}, headers=headers).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "rover-b1", "name": "大棚车", "type": "rover"}, headers=headers)
    return field_id


def _v2_package(field_id: int, front_url: str, under_url: str) -> dict:
    """手写 v2 示例包：结构与 rover 停车模式的产出相同（一个停车点：正面 1 张、叶背补拍 1 次、拍照失败 1 次）。"""
    view = {"side": "under", "pitch_deg": 35.0, "yaw_deg": 0.0, "height_m": 0.2, "fill_light": True}
    blurry = {"method": "iq-rule-v1", "sharpness": 12.5, "mean_luma": 0.41, "clip_high": 0.0, "clip_low": 0.0,
              "backlit": False, "ok": False, "reasons": ["blurry"]}
    good = {**blurry, "sharpness": 180.2, "ok": True, "reasons": []}
    common = {"distance_m": 0.8, "route_chainage_m": 1.2, "distance_source": "configured", "lng": 116.1,
              "lat": 39.1000072, "observation_key": "R01-P004", "position_source": "tag", "weather": None}
    return {
        "schema_version": "2.0",
        "patrol": {
            "field_id": field_id, "device": "rover-b1", "client_package_id": "3f9c2a1b7d4e5f60a1b2c3d4",
            "started_at": "2026-10-08T05:40:00+08:00", "ended_at": "2026-10-08T05:41:30+08:00",
            "track": [[116.1, 39.1000072]], "notes": "rover:rover-b1 mode=stops real/fake=True",
        },
        "capture_points": [
            {**common, "seq": 0, "captured_at": "2026-10-08T05:41:00+08:00", "photo": front_url,
             "view": {"side": "upper", "pitch_deg": 0.0, "yaw_deg": 0.0, "height_m": 0.6, "fill_light": False,
                      "attempt": 1, "accepted": True, "quality": good}},
            {**common, "seq": 1, "captured_at": "2026-10-08T05:41:10+08:00", "photo": under_url,
             "view": {**view, "attempt": 1, "accepted": False, "quality": blurry}},
            {**common, "seq": 2, "captured_at": "2026-10-08T05:41:20+08:00", "photo": None,
             "view": {**view, "pitch_deg": 40.0, "attempt": 2, "accepted": False,
                      "quality": {"method": "iq-rule-v1", "ok": False,
                                  "reasons": ["capture_error: RuntimeError: 读帧失败"]}}},
        ],
    }


def _patrol_count(client) -> int:
    return client.get(f"{BASE}/patrols").json()["total"]


def test_upload_then_exists_and_reupload_is_idempotent(client, media_dir):
    data = _image((40, 160, 60))
    digest = hashlib.sha256(data).hexdigest()
    assert client.get(f"{BASE}/media/exists", params={"sha256": digest}).json() == {"exists": False, "url": None}

    first = _upload(client, data)
    assert first.status_code == 201
    body = first.json()
    assert body == {"url": f"/media/{digest}.jpg", "sha256": digest, "created": True}
    assert (media_dir / f"{digest}.jpg").read_bytes() == data

    again = _upload(client, data, content_type="image/jpeg; charset=binary")
    assert again.status_code == 200 and again.json() == {**body, "created": False}
    found = client.get(f"{BASE}/media/exists", params={"sha256": digest.upper()}).json()
    assert found == {"exists": True, "url": body["url"]}


def test_same_bytes_get_the_same_url_as_base64_ingest(client):
    png = _image((120, 85, 50), fmt="PNG")
    url = _upload(client, png, content_type="image/png").json()["url"]
    assert url.endswith(".png")
    # 扩展名按魔数定，不按 Content-Type：声明错了也落到同一个文件
    assert _upload(client, png, content_type="image/jpeg").json() == {
        "url": url, "sha256": hashlib.sha256(png).hexdigest(), "created": False}
    field_id = _setup(client)
    pkg = _v2_package(field_id, base64.b64encode(png).decode(), "https://example.com/under.jpg")
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=pkg).json()["patrol_id"]
    points = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"]
    assert points[0]["photo_url"] == url


def test_upload_rejects_wrong_type_empty_and_oversize(client, monkeypatch):
    data = _image((10, 10, 10))
    assert _upload(client, data, content_type="application/octet-stream").status_code == 415
    assert client.post(f"{BASE}/media", content=data).status_code == 415
    assert _upload(client, b"").status_code == 422
    monkeypatch.setattr(patrol_schema, "MAX_PHOTO_BYTES", len(data) - 1)
    too_big = _upload(client, data)
    assert too_big.status_code == 413 and "大小上限" in too_big.json()["detail"]


def test_exists_requires_a_sha256(client):
    assert client.get(f"{BASE}/media/exists").status_code == 422
    assert client.get(f"{BASE}/media/exists", params={"sha256": "abc"}).status_code == 422
    assert client.get(f"{BASE}/media/exists", params={"sha256": "g" * 64}).status_code == 422


def test_v2_sample_package_with_uploaded_photos(client):
    field_id = _setup(client)
    front = _upload(client, _image((40, 160, 60))).json()["url"]
    under = _upload(client, _image((60, 140, 50))).json()["url"]
    pkg = _v2_package(field_id, front, under)

    resp = client.post(f"{BASE}/ingest/patrol", json=pkg)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["photos_saved"], body["photos_referenced"], body["duplicate"]) == (0, 2, False)
    points = client.get(f"{BASE}/capture-points?patrol_id={body['patrol_id']}").json()["items"]
    assert [p["photo_url"] for p in points] == [front, under, None]
    assert {p["observation_key"] for p in points} == {"R01-P004"}
    assert [(p["view"]["side"], p["view"]["attempt"], p["view"]["accepted"]) for p in points] == [
        ("upper", 1, True), ("under", 1, False), ("under", 2, False)]
    assert points[0]["position_source"] == "tag" and points[0]["distance_source"] == "configured"

    # 断网后补传同一个包：200 + duplicate，不重复落库
    replay = client.post(f"{BASE}/ingest/patrol", json=copy.deepcopy(pkg))
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    assert replay.json()["patrol_id"] == body["patrol_id"]
    # 同包号内容不同：409，留给人工处理
    changed = copy.deepcopy(pkg)
    changed["capture_points"][1]["photo"] = front
    assert client.post(f"{BASE}/ingest/patrol", json=changed).status_code == 409
    assert _patrol_count(client) == 1


def test_missing_media_reference_is_rejected_before_anything_is_written(client):
    field_id = _setup(client)
    front = _upload(client, _image((40, 160, 60))).json()["url"]
    ghost = f"/media/{'0' * 64}.jpg"
    resp = client.post(f"{BASE}/ingest/patrol", json=_v2_package(field_id, front, ghost))
    assert resp.status_code == 422
    assert ghost in resp.json()["detail"] and "POST /api/v1/media" in resp.json()["detail"]
    assert _patrol_count(client) == 0

    traversal = client.post(f"{BASE}/ingest/patrol", json=_v2_package(field_id, front, "/media/../secret.jpg"))
    assert traversal.status_code == 422 and _patrol_count(client) == 0
    # 外部 URL 不校验，照常接入
    external = client.post(f"{BASE}/ingest/patrol", json=_v2_package(field_id, front, "https://example.com/u.jpg"))
    assert external.status_code == 201


def test_operator_uploads_viewer_only_checks(auth_env):
    client, sessions = auth_env
    _add_user(sessions, "op", "operator")
    _add_user(sessions, "look", "viewer")
    op, viewer = _headers(client, "op"), _headers(client, "look")
    data = _image((40, 160, 60))
    digest = hashlib.sha256(data).hexdigest()
    assert _upload(client, data).status_code == 401
    assert _upload(client, data, headers=viewer).status_code == 403
    assert _upload(client, data, headers=op).status_code == 201
    exists = client.get(f"{BASE}/media/exists", params={"sha256": digest}, headers=viewer)
    assert exists.status_code == 200 and exists.json()["exists"] is True
