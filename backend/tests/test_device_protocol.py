"""设备注册、心跳、事件与故障注入协议测试。"""

from conftest import png_b64


BASE = "/api/v1"


def _register(client, code="proto-01"):
    response = client.post(
        f"{BASE}/devices/register",
        json={"code": code, "name": "协议测试车", "type": "rover", "model": "pi3b"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _patrol(client, code="proto-01"):
    field = client.post(
        f"{BASE}/fields",
        json={
            "name": "设备协议测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    )
    assert field.status_code == 201, field.text
    package = {
        "patrol": {
            "field_id": field.json()["id"],
            "device": code,
            "started_at": "2026-09-24T08:00:00+00:00",
            "ended_at": "2026-09-24T08:05:00+00:00",
        },
        "capture_points": [
            {
                "seq": 0,
                "distance_m": 0,
                "lng": 10.1,
                "lat": 10.1,
                "captured_at": "2026-09-24T08:00:00+00:00",
                "photo": png_b64((40, 160, 60)),
            }
        ],
    }
    response = client.post(f"{BASE}/ingest/patrol", json=package)
    assert response.status_code == 201, response.text
    return response.json()["patrol_id"]


def test_register_is_idempotent_and_updates_device_description(client):
    first = _register(client)
    second = client.post(
        f"{BASE}/devices/register",
        json={"code": "proto-01", "name": "协议测试车二号", "type": "rover", "status": "active"},
    )

    assert second.status_code == 200, second.text
    assert second.json()["id"] == first["id"]
    assert second.json()["name"] == "协议测试车二号"
    assert second.json()["status"] == "active"


def test_heartbeat_persists_protocol_state_and_is_idempotent(client):
    device = _register(client)
    payload = {
        "client_heartbeat_id": "hb-0001",
        "observed_at": "2026-09-24T08:00:00+00:00",
        "status": "active",
        "execution_phase": "moving",
        "position_source": "encoder",
        "queue_size": 3,
        "battery_pct": 82.5,
        "temperature_c": 43.2,
        "payload": {"error_codes": []},
    }
    first = client.post(f"{BASE}/devices/{device['id']}/heartbeat", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["execution_phase"] == "moving"
    assert client.get(f"{BASE}/devices/{device['id']}").json()["status"] == "active"

    duplicate = client.post(f"{BASE}/devices/{device['id']}/heartbeat", json=payload)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["id"] == first.json()["id"]
    assert len(client.get(f"{BASE}/devices/{device['id']}/heartbeats").json()) == 1

    missing_mission = client.post(
        f"{BASE}/devices/{device['id']}/heartbeat",
        json={"mission_id": 999, "execution_phase": "moving"},
    )
    assert missing_mission.status_code == 404


def test_device_event_and_mission_event_are_traceable(client):
    device = _register(client)
    event = client.post(
        f"{BASE}/devices/{device['id']}/events",
        json={
            "client_event_id": "evt-stop-1",
            "event_type": "emergency_stop",
            "severity": "critical",
            "occurred_at": "2026-09-24T08:02:00+00:00",
            "payload": {"source": "watchdog"},
        },
    )
    assert event.status_code == 201, event.text
    assert event.json()["event_type"] == "emergency_stop"
    assert client.get(f"{BASE}/devices/{device['id']}").json()["status"] == "maintenance"

    duplicate = client.post(
        f"{BASE}/devices/{device['id']}/events",
        json={"client_event_id": "evt-stop-1", "event_type": "emergency_stop", "severity": "critical"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == event.json()["id"]

    mission_id = _patrol(client)
    mission_event = client.post(
        f"{BASE}/missions/{mission_id}/events",
        json={
            "event_type": "sample_persisted",
            "severity": "info",
            "client_event_id": "evt-sample-1",
            "payload": {"seq": 0},
        },
    )
    assert mission_event.status_code == 201, mission_event.text
    assert mission_event.json()["mission_id"] == mission_id
    assert len(client.get(f"{BASE}/missions/{mission_id}/events").json()) == 1

    other_device = _register(client, code="proto-02")
    mismatch = client.post(
        f"{BASE}/missions/{mission_id}/events",
        json={"device_id": other_device["id"], "event_type": "sample_persisted"},
    )
    assert mismatch.status_code == 409


def test_fault_injection_is_a_replayable_event_and_updates_platform_state(client):
    device = _register(client, code="fault-01")
    injected = client.post(
        f"{BASE}/devices/{device['id']}/fault-injection",
        json={
            "client_event_id": "fault-1",
            "fault_type": "network_timeout",
            "active": True,
            "payload": {"timeout_ms": 3000},
        },
    )
    assert injected.status_code == 201, injected.text
    body = injected.json()
    assert body["is_fault_injected"] is True
    assert body["fault_type"] == "network_timeout"
    assert body["fault_active"] is True
    assert client.get(f"{BASE}/devices/{device['id']}").json()["status"] == "maintenance"

    cleared = client.post(
        f"{BASE}/devices/{device['id']}/fault-injection",
        json={
            "client_event_id": "fault-1-clear",
            "fault_type": "network_timeout",
            "active": False,
        },
    )
    assert cleared.status_code == 201, cleared.text
    assert cleared.json()["fault_active"] is False
    assert client.get(f"{BASE}/devices/{device['id']}").json()["status"] == "idle"
    events = client.get(f"{BASE}/devices/{device['id']}/events?fault_injected=true").json()
    assert len(events) == 2
