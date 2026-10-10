"""计划 0007 P0-2（决策 D26）：车端时钟状态随包上报，平台按时间戳和时钟状态给出时间告警，只提示不拒收。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.patrol import PatrolPackageIn
from app.services import ingest as ingest_service
from app.services.clock_check import (
    FUTURE_TOLERANCE_S,
    OFFSET_WARN_S,
    clock_warnings,
    heartbeat_warnings,
    patrol_warnings,
    timestamp_warnings,
)
from conftest import png_b64

BASE = "/api/v1"
NOW = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
BOUNDARY = {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10.001], [10, 10]]]}


def _codes(warnings):
    return [w["code"] for w in warnings]


# ---------------------------------------------------------------- 规则（纯函数）


def test_timestamps_in_the_future_or_before_2020_are_flagged():
    assert timestamp_warnings([NOW - timedelta(days=3), NOW + timedelta(seconds=FUTURE_TOLERANCE_S)], NOW) == []
    ahead = timestamp_warnings([NOW + timedelta(hours=2, minutes=5)], NOW)
    assert _codes(ahead) == ["future_timestamp"] and "约 2 小时 5 分" in ahead[0]["message"]
    stale = timestamp_warnings([datetime(1970, 1, 1, 0, 3, tzinfo=timezone.utc), NOW], NOW)
    assert _codes(stale) == ["implausible_timestamp"] and "1970-01-01" in stale[0]["message"]
    # 无时区按 UTC 解释（D9），不因比较带时区与不带时区的时间而出错
    assert timestamp_warnings([datetime(2026, 10, 10, 5, 0)], NOW) == []


@pytest.mark.parametrize("clock,codes", [
    (None, []),
    ({"synced": True, "offset_s": 0.4}, []),
    ({"synced": False, "offset_s": -OFFSET_WARN_S}, []),  # 量到了且在阈值内：未对时也不报
    ({"synced": True, "offset_s": OFFSET_WARN_S + 1}, ["clock_offset"]),
    ({"synced": False, "offset_s": None}, ["clock_unsynced"]),  # 离线、系统也说没对时
    ({"synced": None, "offset_s": None}, []),  # 什么都不知道：不报
])
def test_clock_status_rules(clock, codes):
    assert _codes(clock_warnings(clock)) == codes


def test_offset_message_says_which_way():
    fast = clock_warnings({"offset_s": 3 * 86400})[0]["message"]
    slow = clock_warnings({"offset_s": -125})[0]["message"]
    assert "快 约 3 天" in fast and "慢 约 2 分钟" in slow
    assert "慢 约 57 年" in clock_warnings({"offset_s": -1_791_638_100})[0]["message"]  # 停在 1970 年


def test_patrol_warnings_combine_timestamps_and_clock():
    warnings = patrol_warnings(
        started_at=NOW + timedelta(hours=1), ended_at=NOW + timedelta(hours=2), captured=[NOW + timedelta(hours=1)],
        clock={"synced": True, "offset_s": 3600.0}, received_at=NOW,
    )
    assert _codes(warnings) == ["future_timestamp", "clock_offset"]


def test_heartbeat_skew_used_only_without_measured_offset():
    skew, warnings = heartbeat_warnings(observed_at=NOW + timedelta(minutes=10), clock=None, received_at=NOW)
    assert skew == 600 and _codes(warnings) == ["heartbeat_skew"]
    # 车端量过时间差（更准）就以它为准，心跳到达延迟不算
    _, warnings = heartbeat_warnings(observed_at=NOW - timedelta(minutes=10), clock={"offset_s": 0.2},
                                     received_at=NOW)
    assert warnings == []
    skew, warnings = heartbeat_warnings(observed_at=None, clock=None, received_at=NOW)
    assert skew is None and warnings == []
    # 停在 1970 年：只报一条「没对时」，不再叠一条巨大的时间差
    _, warnings = heartbeat_warnings(observed_at=datetime(1970, 1, 1, tzinfo=timezone.utc), clock=None,
                                     received_at=NOW)
    assert _codes(warnings) == ["implausible_timestamp"] and "心跳时间" in warnings[0]["message"]


# ---------------------------------------------------------------- 协议与接口


def _setup(client):
    field_id = client.post(f"{BASE}/fields", json={"name": "时钟测试棚", "boundary": BOUNDARY,
                                                   "facility_type": "solar_greenhouse"}).json()["id"]
    device_id = client.post(f"{BASE}/devices", json={"code": "gh-clock", "name": "大棚车", "type": "rover"}).json()["id"]
    return field_id, device_id


def _package(field_id, *, start: datetime, clock=None, version="2.0", cpid="gh-clock-1"):
    patrol = {"field_id": field_id, "device": "gh-clock", "started_at": start.isoformat()}
    if version == "2.0":
        patrol["client_package_id"] = cpid
    if clock is not None:
        patrol["clock"] = clock
    return {"schema_version": version, "patrol": patrol, "capture_points": [
        {"seq": seq, "lng": 10.0005, "lat": 10.0005, "captured_at": (start + timedelta(seconds=seq)).isoformat(),
         "photo": png_b64((40 + seq, 150, 60))} for seq in range(2)
    ]}


def test_clock_is_a_v2_header_field_and_appears_in_schema_export(client):
    field_id, _ = _setup(client)
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, start=start, version="1.0",
                                                              clock={"synced": True}))
    assert resp.status_code == 422 and "patrol.clock" in resp.text
    bad = _package(field_id, start=start, clock={"synced": True, "source": "sundial"})
    assert client.post(f"{BASE}/ingest/patrol", json=bad).status_code == 422
    schema = client.get(f"{BASE}/ingest/patrol-schema").json()
    assert "clock" in schema["$defs"]["PatrolHeaderPayload"]["properties"]
    assert set(schema["$defs"]["ClockPayload"]["properties"]) == {"synced", "source", "offset_s", "measured_at"}


def test_ingest_stores_clock_and_warnings_without_rejecting(client):
    field_id, _ = _setup(client)
    start = datetime.now(timezone.utc) + timedelta(hours=3)  # 车端时钟快了 3 小时
    clock = {"synced": False, "source": "ntp", "offset_s": 10800.5, "measured_at": start.isoformat()}
    resp = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, start=start, clock=clock))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["warnings"]) == 2 and "比平台接收时间还晚" in body["warnings"][0]
    assert "快 约 3 小时" in body["warnings"][1]

    detail = client.get(f"{BASE}/patrols/{body['patrol_id']}").json()
    assert detail["clock"]["offset_s"] == 10800.5 and detail["clock"]["source"] == "ntp"
    assert [w["code"] for w in detail["time_warnings"]] == ["future_timestamp", "clock_offset"]
    listed = client.get(f"{BASE}/patrols").json()["items"][0]
    assert [w["code"] for w in listed["time_warnings"]] == ["future_timestamp", "clock_offset"]

    # 同包号重传：回执带上原来的告警，不重复入库
    again = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, start=start, clock=clock))
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert again.json()["warnings"] == body["warnings"]


def test_clean_package_has_no_warnings_and_old_rows_read_as_empty(client):
    field_id, _ = _setup(client)
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    body = client.post(f"{BASE}/ingest/patrol", json=_package(
        field_id, start=start, clock={"synced": True, "source": "chrony", "offset_s": -0.3})).json()
    assert body["warnings"] == []
    detail = client.get(f"{BASE}/patrols/{body['patrol_id']}").json()
    assert detail["time_warnings"] == [] and detail["clock"]["synced"] is True
    v1 = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, start=start + timedelta(minutes=5),
                                                            version="1.0")).json()
    assert v1["warnings"] == []
    assert client.get(f"{BASE}/patrols/{v1['patrol_id']}").json()["clock"] is None


def test_digest_of_packages_without_clock_is_unchanged():
    """升级前收下的包（没有 clock）重传时摘要必须不变，否则会被当成包号冲突（409）。"""
    package = PatrolPackageIn.model_validate({
        "schema_version": "2.0",
        "patrol": {"field_id": 1, "device": "gh-01", "started_at": "2026-10-01T06:00:00+08:00",
                   "client_package_id": "gh-01-20261001"},
        "capture_points": [{"seq": 0, "lng": 10.0005, "lat": 10.0005, "captured_at": "2026-10-01T06:00:00+08:00",
                            "photo": "/media/abc.jpg", "observation_key": "R01-P001", "view": {"side": "under"}}],
    })
    # 在加 clock 之前的代码（fb14cae）上对同一个包算出的摘要
    assert ingest_service.package_digest(package) == "c37e1e3dab722414e83c80ad57db0c4819166055f43e42f84641e934b1d56ddc"
    with_clock = package.model_copy(update={"patrol": package.patrol.model_copy(
        update={"clock": {"synced": True}})})
    assert ingest_service.package_digest(with_clock) != ingest_service.package_digest(package)


def test_heartbeat_records_skew_and_warnings(client):
    _, device_id = _setup(client)
    late = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    resp = client.post(f"{BASE}/devices/{device_id}/heartbeat", json={"client_heartbeat_id": "hb-1",
                                                                       "observed_at": late})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert 1790 < body["clock_skew_s"] < 1810 and [w["code"] for w in body["time_warnings"]] == ["heartbeat_skew"]

    measured = client.post(f"{BASE}/devices/{device_id}/heartbeat", json={
        "client_heartbeat_id": "hb-2", "observed_at": datetime.now(timezone.utc).isoformat(),
        "clock": {"synced": False, "source": "chrony", "offset_s": None}}).json()
    assert [w["code"] for w in measured["time_warnings"]] == ["clock_unsynced"]
    assert measured["clock"]["source"] == "chrony"

    # 没填 observed_at：平台补当前时间，不算时间差
    default = client.post(f"{BASE}/devices/{device_id}/heartbeat", json={"client_heartbeat_id": "hb-3"}).json()
    assert default["clock_skew_s"] is None and default["time_warnings"] == []
    latest = client.get(f"{BASE}/devices/{device_id}/heartbeats?limit=5").json()
    assert {h["client_heartbeat_id"] for h in latest} == {"hb-1", "hb-2", "hb-3"}


def test_health_reports_server_time(client):
    body = client.get(f"{BASE}/health").json()
    server = datetime.fromisoformat(body["server_time"])
    assert server.tzinfo is not None and abs((server - datetime.now(timezone.utc)).total_seconds()) < 60
