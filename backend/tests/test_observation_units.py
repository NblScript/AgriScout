"""计划 0014：株档案、协议 v2 最小子集、上传幂等、按株关联、单株时间线。"""
import base64
import io
import json
from datetime import datetime, timezone

import pytest
from PIL import Image

from app.core.db import get_session_factory
from app.main import app
from app.models import Patrol
from app.schemas.patrol import PatrolPackageIn
from app.services import ingest as ingest_service
from app.services.observation_units import parse_unit_key
from app.services.risk_inputs import build_region_series
from app.services.risk_model import image_table, model_path, save_model_file, typed_neighbor_map
from conftest import png_b64
from test_auth import _add_user, _headers
from test_risk_model import _doc, _generate, _mini_season, model_dir  # noqa: F401  夹具复用

BASE = "/api/v1"
GREEN, BROWN = png_b64((40, 160, 60)), png_b64((120, 85, 50))
BOUNDARY = {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10.001], [10, 10]]]}


def _setup(client, name="株档案测试田", device="gh-01"):
    field_id = client.post(f"{BASE}/fields", json={
        "name": name, "boundary": BOUNDARY, "facility_type": "plastic_tunnel",
    }).json()["id"]
    client.post(f"{BASE}/devices", json={"code": device, "name": "大棚车", "type": "rover"})
    return field_id


def _point(seq, key=None, *, day="2026-10-01", hour=6, side="upper", attempt=1, photo=GREEN, quality_ok=True):
    point = {"seq": seq, "lng": 10.0005, "lat": 10.0005, "captured_at": f"{day}T{hour:02d}:{seq:02d}:00+08:00",
             "photo": photo}
    if key is not None:
        point.update({
            "observation_key": key, "route_chainage_m": 0.4 * seq, "distance_source": "encoder",
            "position_source": "tag",
            "view": {"side": side, "pitch_deg": 35 if side == "under" else 0, "attempt": attempt,
                     "accepted": quality_ok, "quality": {"method": "iq-rule-v1", "ok": quality_ok}},
        })
    return point


def _package(field_id, points, *, device="gh-01", day="2026-10-01", cpid=None, version="2.0"):
    package = {
        "schema_version": version,
        "patrol": {"field_id": field_id, "device": device, "started_at": f"{day}T06:00:00+08:00"},
        "capture_points": points,
    }
    if cpid is not None:
        package["patrol"]["client_package_id"] = cpid
    return package


def _session(client):
    """与被测应用同一个库的会话（conftest 用 dependency_overrides 换了会话工厂）。"""
    return app.dependency_overrides[get_session_factory]()()


# ---------------------------------------------------------------- 协议


def test_v2_fields_require_schema_version_2(client):
    field_id = _setup(client)
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R01-P001")], version="1.0"))
    assert resp.status_code == 422
    assert "schema_version" in resp.text
    no_version = _package(field_id, [_point(0)], cpid="pkg-1")
    del no_version["schema_version"]
    assert client.post(f"{BASE}/ingest/patrol", json=no_version).status_code == 422


def test_view_quality_ok_must_be_bool(client):
    field_id = _setup(client)
    point = _point(0, "R01-P001")
    point["view"]["quality"] = {"ok": "yes"}
    assert client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [point])).status_code == 422


def test_v2_point_fields_round_trip_to_point_api(client):
    field_id = _setup(client)
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R02-P005", side="under")]))
    assert resp.status_code == 201, resp.text
    patrol_id = resp.json()["patrol_id"]
    point = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"][0]
    assert point["observation_key"] == "R02-P005"
    assert point["observation_unit_id"] is not None
    assert point["position_source"] == "tag" and point["distance_source"] == "encoder"
    assert point["route_chainage_m"] == 0.0
    assert point["view"]["side"] == "under" and point["view"]["quality"]["ok"] is True
    detail = client.get(f"{BASE}/patrols/{patrol_id}").json()
    assert detail["schema_version"] == "2.0"
    assert client.get(f"{BASE}/fields/{field_id}").json()["facility_type"] == "plastic_tunnel"


def test_v1_points_have_empty_v2_fields(client):
    field_id = _setup(client)
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0)], version="1.0"))
    assert resp.status_code == 201
    point = client.get(f"{BASE}/capture-points?patrol_id={resp.json()['patrol_id']}").json()["items"][0]
    assert point["observation_key"] is None and point["view"] is None
    assert client.get(f"{BASE}/patrols/{resp.json()['patrol_id']}").json()["schema_version"] == "1.0"


def test_schema_export_contains_v2_fields(client):
    schema = client.get(f"{BASE}/ingest/patrol-schema").json()
    assert "schema_version" in schema["properties"]
    assert "client_package_id" in schema["$defs"]["PatrolHeaderPayload"]["properties"]
    point = schema["$defs"]["CapturePointPayload"]["properties"]
    assert {"observation_key", "route_chainage_m", "distance_source", "position_source", "view"} <= set(point)
    assert "quality" in schema["$defs"]["ViewPayload"]["properties"]


# ---------------------------------------------------------------- 幂等


def test_same_package_id_same_content_is_duplicate(client):
    field_id = _setup(client)
    package = _package(field_id, [_point(0, "R01-P001"), _point(1, "R01-P002")], cpid="rover-pkg-1")
    first = client.post(f"{BASE}/ingest/patrol", json=package)
    assert first.status_code == 201 and first.json()["duplicate"] is False
    again = client.post(f"{BASE}/ingest/patrol", json=package)
    assert again.status_code == 200
    body = again.json()
    assert body["duplicate"] is True and body["patrol_id"] == first.json()["patrol_id"]
    assert body["capture_points"] == 2 and body["photos_saved"] == 0
    assert client.get(f"{BASE}/patrols").json()["total"] == 1


def test_same_package_id_different_content_conflicts(client):
    field_id = _setup(client)
    first = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R01-P001")], cpid="pkg-x"))
    changed = _package(field_id, [_point(0, "R01-P001", photo=BROWN)], cpid="pkg-x", day="2026-10-02")
    resp = client.post(f"{BASE}/ingest/patrol", json=changed)
    assert resp.status_code == 409
    assert f"patrol_id={first.json()['patrol_id']}" in resp.json()["detail"]


def test_package_id_is_scoped_per_device(client):
    field_id = _setup(client)
    client.post(f"{BASE}/devices", json={"code": "gh-02", "name": "二号车", "type": "rover"})
    a = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0)], cpid="same"))
    b = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0)], cpid="same", device="gh-02"))
    assert a.status_code == b.status_code == 201
    assert a.json()["patrol_id"] != b.json()["patrol_id"]


def test_without_package_id_old_triple_duplicate_rule_applies(client):
    field_id = _setup(client)
    package = _package(field_id, [_point(0)], version="1.0")
    assert client.post(f"{BASE}/ingest/patrol", json=package).status_code == 201
    assert client.post(f"{BASE}/ingest/patrol", json=package).status_code == 409


def test_unique_constraint_race_resolves_to_duplicate(client, monkeypatch):
    """并发重传：查询时还没有，插入时撞上 (设备, 包号) 唯一约束 → 重新判定为 duplicate。"""
    field_id = _setup(client)
    package = _package(field_id, [_point(0, "R01-P001")], cpid="race-1")
    digest = ingest_service.package_digest(PatrolPackageIn.model_validate(package))
    with _session(client) as db:  # 「对方」已落库的同键记录
        device_id = client.get(f"{BASE}/devices").json()[0]["id"]
        db.add(Patrol(field_id=field_id, device_id=device_id, client_package_id="race-1", package_sha256=digest,
                      schema_version="2.0", started_at=datetime(2026, 9, 30, tzinfo=timezone.utc)))
        db.commit()
        existing_id = db.query(Patrol).one().id

    real = ingest_service._replay_result
    calls = {"n": 0}

    def first_miss(*args):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*args)

    monkeypatch.setattr(ingest_service, "_replay_result", first_miss)
    resp = client.post(f"{BASE}/ingest/patrol", json=package)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"patrol_id": existing_id, "capture_points": 0, "photos_saved": 0,
                           "photos_referenced": 0, "duplicate": True}
    assert calls["n"] == 2


# ---------------------------------------------------------------- 株档案


def test_ingest_auto_creates_units_for_review(client):
    field_id = _setup(client)
    client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R03-P017"), _point(1, "east.gate-7")]))
    units = client.get(f"{BASE}/fields/{field_id}/observation-units?created_from=ingest").json()
    by_key = {u["key"]: u for u in units}
    assert set(by_key) == {"R03-P017", "east.gate-7"}
    assert (by_key["R03-P017"]["row_no"], by_key["R03-P017"]["position_no"]) == (3, 17)
    assert by_key["east.gate-7"]["row_no"] is None and by_key["east.gate-7"]["position_no"] is None
    # 第二趟同株不再新建
    client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R03-P017", day="2026-10-02")], day="2026-10-02"))
    assert len(client.get(f"{BASE}/fields/{field_id}/observation-units").json()) == 2


def test_parse_unit_key():
    assert parse_unit_key("R01-P001") == (1, 1)
    assert parse_unit_key("R12-P345") == (12, 345)
    assert parse_unit_key("R00-P001") is None
    assert parse_unit_key("R1-P1") is None
    assert parse_unit_key("plant-7") is None


def test_bulk_create_is_idempotent_and_filters(client):
    field_id = _setup(client)
    body = {"rows": [{"row_no": 1, "plants": 3, "spacing_m": 0.4, "start_chainage_m": 1.0},
                     {"row_no": 2, "plants": 2, "spacing_m": 0.5}]}
    assert client.post(f"{BASE}/fields/{field_id}/observation-units/bulk", json=body).json() == \
        {"created": 5, "skipped": 0}
    body["rows"][1]["plants"] = 4
    assert client.post(f"{BASE}/fields/{field_id}/observation-units/bulk", json=body).json() == \
        {"created": 2, "skipped": 5}
    row1 = client.get(f"{BASE}/fields/{field_id}/observation-units?row_no=1").json()
    assert [u["key"] for u in row1] == ["R01-P001", "R01-P002", "R01-P003"]
    assert [u["chainage_m"] for u in row1] == [1.0, 1.4, 1.8]
    assert {u["created_from"] for u in row1} == {"bulk"}


def test_manual_create_patch_and_conflicts(client):
    field_id = _setup(client)
    created = client.post(f"{BASE}/fields/{field_id}/observation-units", json={"key": "R01-P001", "tag_code": "QR1"})
    assert created.status_code == 201 and created.json()["created_from"] == "manual"
    assert client.post(f"{BASE}/fields/{field_id}/observation-units", json={"key": "R01-P001"}).status_code == 409
    assert client.post(f"{BASE}/fields/{field_id}/observation-units",
                       json={"key": "R01-P002", "tag_code": "QR1"}).status_code == 409
    assert client.post(f"{BASE}/fields/{field_id}/observation-units", json={"key": "bad key"}).status_code == 422
    unit_id = created.json()["id"]
    patched = client.patch(f"{BASE}/observation-units/{unit_id}", json={"status": "retired", "note": "拔除"}).json()
    assert patched["status"] == "retired" and patched["note"] == "拔除"
    assert client.patch(f"{BASE}/observation-units/{unit_id}", json={"status": None}).status_code == 422
    assert client.get(f"{BASE}/fields/{field_id}/observation-units?status=retired").json()[0]["id"] == unit_id
    assert client.get(f"{BASE}/fields/999/observation-units").status_code == 404


def test_field_facility_type_validated(client):
    field_id = _setup(client)
    assert client.patch(f"{BASE}/fields/{field_id}", json={"facility_type": "solar_greenhouse"}).status_code == 200
    assert client.patch(f"{BASE}/fields/{field_id}", json={"facility_type": "barn"}).status_code == 422


# ---------------------------------------------------------------- 按株关联


def test_points_aggregate_by_unit_and_form_history(client):
    field_id = _setup(client)
    day1 = [_point(0, "R01-P001"), _point(1, "R01-P001", side="under", photo=BROWN), _point(2, "R01-P002")]
    client.post(f"{BASE}/ingest/patrol", json=_package(field_id, day1))
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R01-P001", day="2026-10-02")], day="2026-10-02"))
    with _session(client) as db:
        patrol = db.get(Patrol, resp.json()["patrol_id"])
        inputs = build_region_series(db, patrol, cell_m=2.5, history_days=30)
    key = f"field-{field_id}/unit/R01-P001"
    assert set(inputs.series) == {key}
    series = inputs.series[key]
    assert len(series.history) == 1 and series.history[0]["points"] == 2
    assert series.history[0]["risk_score"] > series.current["risk_score"]  # 前一天叶背是棕图
    assert inputs.coords[key] == ("unit", 1, 1)


def test_unit_neighbors_are_adjacent_plants_and_never_grid():
    coords = {
        "u/R02-P005": ("unit", 2, 5), "u/R02-P006": ("unit", 2, 6), "u/R02-P007": ("unit", 2, 7),
        "u/R03-P005": ("unit", 3, 5), "u/R04-P005": ("unit", 4, 5),
        "g/2_5": ("grid", 2, 5), "g/2_6": ("grid", 2, 6),
    }
    neighbors = typed_neighbor_map(coords)
    assert sorted(neighbors["u/R02-P006"]) == ["u/R02-P005", "u/R02-P007", "u/R03-P005"]
    assert sorted(neighbors["u/R02-P005"]) == ["u/R02-P006", "u/R03-P005"]
    assert "u/R04-P005" not in neighbors["u/R02-P005"]  # 隔一垄不算
    assert neighbors["g/2_5"] == ["g/2_6"]  # 网格只和网格相邻


def test_custom_key_unit_has_no_neighbors(client):
    field_id = _setup(client)
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "gate-a"), _point(1, "R01-P001")]))
    with _session(client) as db:
        inputs = build_region_series(db, db.get(Patrol, resp.json()["patrol_id"]), cell_m=2.5, history_days=30)
        _, _, coords = image_table(inputs, resp.json()["patrol_id"])
    assert f"field-{field_id}/unit/gate-a" in inputs.series
    assert f"field-{field_id}/unit/gate-a" not in coords
    assert typed_neighbor_map(coords)[f"field-{field_id}/unit/R01-P001"] == []


# 改动前（网格关联、parse_key 取坐标）在 _mini_season 最后一趟上的 risk-lr 特征，逐位钉住
GRID_ONLY_FEATURES = {
    "0_1": {"img_delta": 0.0, "img_hist_max": 0.0, "img_now": 0.0, "nbr_delta": 0.0, "nbr_now": 1.0},
    "1_1": {"img_delta": 0.0, "img_hist_max": 1.0, "img_now": 1.0, "nbr_delta": 0.0, "nbr_now": 1.0},
    "1_2": {"img_delta": 1.0, "img_hist_max": 0.0, "img_now": 1.0, "nbr_delta": 0.0, "nbr_now": 1.0},
    "2_2": {"img_delta": 0.0, "img_hist_max": 0.0, "img_now": 0.0, "nbr_delta": 0.0, "nbr_now": 1.0},
}
GRID_ONLY_CONTRIBUTIONS_0_1 = {"img_delta": 0.0, "img_hist_max": 0.0, "img_now": 0.0,
                               "nbr_delta": 0.6988, "nbr_now": 17.7489}


def test_grid_only_risk_lr_output_unchanged(client, model_dir):  # noqa: F811
    save_model_file(_doc(), model_path("risk-lr-test"))
    _, patrols = _mini_season(client)
    preds = {p["observation_key"].rsplit("/", 1)[-1]: p for p in _generate(client, patrols[-1]["patrol_id"]).json()}
    assert len(preds) == 8
    for cell, features in GRID_ONLY_FEATURES.items():
        assert preds[cell]["evidence"]["feature_values"] == features, cell
    assert preds["0_1"]["evidence"]["contributions"] == GRID_ONLY_CONTRIBUTIONS_0_1
    assert preds["1_1"]["evidence"]["region"]["method"] == "grid-v0"


def test_unit_region_predictions_use_unit_keys(client):
    field_id = _setup(client)
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R01-P001"), _point(1, "R01-P002")]))
    preds = client.post(f"{BASE}/patrols/{resp.json()['patrol_id']}/risk-predictions/generate",
                        json={"target_event": "霜霉病显症", "forecast_hours": 72}).json()
    assert {p["observation_key"] for p in preds} == {f"field-{field_id}/unit/R01-P001", f"field-{field_id}/unit/R01-P002"}
    region = preds[0]["evidence"]["region"]
    assert region["method"] == "observation-unit" and region["cell_m"] is None


# ---------------------------------------------------------------- 时间线


def _jpeg_b64(gray: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (gray, gray, gray)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


def _timeline_fixture(client):
    field_id = _setup(client)
    day1 = [_point(0, "R01-P001"), _point(1, "R01-P001", side="under", quality_ok=False, photo=_jpeg_b64(250)),
            _point(2, "R01-P001", side="under", attempt=2)]
    p1 = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, day1)).json()["patrol_id"]
    client.post(f"{BASE}/ingest/patrol", json=_package(field_id, [_point(0, "R01-P001", day="2026-10-03")], day="2026-10-03"))
    unit_id = client.get(f"{BASE}/fields/{field_id}/observation-units").json()[0]["id"]
    return field_id, unit_id, p1


def test_timeline_groups_photos_by_field_date(client):
    field_id, unit_id, p1 = _timeline_fixture(client)
    point_ids = [p["id"] for p in client.get(f"{BASE}/capture-points?patrol_id={p1}").json()["items"]]
    assert client.post(f"{BASE}/capture-points/{point_ids[1]}/annotations",
                       json={"label": "suspected_disease", "annotator_name": "王老师"}).status_code == 201
    client.post(f"{BASE}/patrols/{p1}/risk-predictions/generate", json={"target_event": "霜霉病显症", "forecast_hours": 72})

    timeline = client.get(f"{BASE}/observation-units/{unit_id}/timeline").json()
    assert timeline["unit"]["key"] == "R01-P001"
    assert [d["field_date"] for d in timeline["days"]] == ["2026-10-01", "2026-10-03"]
    first = timeline["days"][0]
    assert [(p["view"]["side"], p["view"]["attempt"]) for p in first["photos"]] == [("upper", 1), ("under", 1), ("under", 2)]
    assert first["photos"][1]["view"]["quality"]["ok"] is False
    assert first["photos"][0]["analysis"]["analyzer_version"] == "placeholder-color-v0"
    # 平台按 iq-rule-v1 测的质量（0016-A）随分析结果进时间线；纯色合成图没有纹理，判为模糊
    assert first["photos"][0]["analysis"]["image_quality"]["method"] == "iq-rule-v1"
    assert "blurry" in first["photos"][0]["analysis"]["image_quality"]["reasons"]
    assert [a["label"] for a in first["annotations"]] == ["suspected_disease"]
    assert len(first["predictions"]) == 3 and first["predictions"][0]["follow_up_status"] is None
    assert len(timeline["days"][1]["photos"]) == 1

    narrow = client.get(f"{BASE}/observation-units/{unit_id}/timeline?days=1").json()
    assert [d["field_date"] for d in narrow["days"]] == ["2026-10-03"]
    assert client.get(f"{BASE}/observation-units/999/timeline").status_code == 404


def test_timeline_is_readable_by_viewer_but_writes_are_forbidden(auth_env):
    client, session_factory = auth_env
    _add_user(session_factory, "op", "operator")
    _add_user(session_factory, "look", "viewer")
    op, viewer = _headers(client, "op"), _headers(client, "look")
    field_id = client.post(f"{BASE}/fields", json={"name": "权限田", "boundary": BOUNDARY}, headers=op).json()["id"]
    unit = client.post(f"{BASE}/fields/{field_id}/observation-units", json={"key": "R01-P001"}, headers=op).json()

    assert client.get(f"{BASE}/observation-units/{unit['id']}/timeline", headers=viewer).status_code == 200
    assert client.get(f"{BASE}/fields/{field_id}/observation-units", headers=viewer).status_code == 200
    assert client.post(f"{BASE}/fields/{field_id}/observation-units", json={"key": "R01-P002"},
                       headers=viewer).status_code == 403
    assert client.post(f"{BASE}/fields/{field_id}/observation-units/bulk",
                       json={"rows": [{"row_no": 1, "plants": 1, "spacing_m": 0.4}]}, headers=viewer).status_code == 403
    assert client.patch(f"{BASE}/observation-units/{unit['id']}", json={"note": "x"}, headers=viewer).status_code == 403
    assert json.loads(client.get(f"{BASE}/observation-units/{unit['id']}/timeline").text)["detail"] == "请先登录"
