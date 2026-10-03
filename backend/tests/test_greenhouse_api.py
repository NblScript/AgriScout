"""计划 0015：环境上报与查询、每株状态、巡检计划接口。"""
from datetime import datetime, timedelta, timezone

from app.core.timeutil import FIELD_TZ
from test_auth import _add_user, _headers
from test_observation_units import BOUNDARY, BROWN, _package, _point, _setup

BASE = "/api/v1"


def _readings(start: datetime, hours: int, temp: float, rh: float, step_min: int = 30):
    return [{"observed_at": (start + timedelta(minutes=step_min * k)).isoformat(), "temp_c": temp, "humidity_pct": rh}
            for k in range(hours * 60 // step_min)]


def _upload(client, field_id, readings, sensor="th-01", **extra):
    return client.post(f"{BASE}/fields/{field_id}/env-readings",
                       json={"sensor_key": sensor, "readings": readings, **extra})


# ---------------------------------------------------------------- 环境上报与查询


def test_env_upload_skips_duplicates_in_request_and_db(client):
    field_id = _setup(client)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    batch = _readings(start, 2, 18, 90)
    first = _upload(client, field_id, batch + batch[:1])
    assert first.status_code == 200 and first.json() == {"inserted": 4, "skipped": 1}
    again = _upload(client, field_id, batch)
    assert again.json() == {"inserted": 0, "skipped": 4}
    other_sensor = _upload(client, field_id, batch, sensor="th-02")
    assert other_sensor.json() == {"inserted": 4, "skipped": 0}


def test_env_naive_time_is_utc_and_aware_time_is_converted(client):
    field_id = _setup(client)
    naive = {"observed_at": "2026-10-01T10:00:00", "temp_c": 20, "humidity_pct": 80}
    same_moment = {"observed_at": "2026-10-01T18:00:00+08:00", "temp_c": 21, "humidity_pct": 81}
    assert _upload(client, field_id, [naive]).json() == {"inserted": 1, "skipped": 0}
    assert _upload(client, field_id, [same_moment]).json() == {"inserted": 0, "skipped": 1}
    env = client.get(f"{BASE}/fields/{field_id}/env").json()
    filled = [h for h in env["hourly"] if not h["missing"]]
    assert len(filled) == 1 and filled[0]["hour"].startswith("2026-10-01T10:00:00")
    assert filled[0]["temp_c"] == 20


def test_env_upload_limits_and_validation(client):
    field_id = _setup(client)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    too_many = [{"observed_at": (start + timedelta(seconds=k)).isoformat(), "temp_c": 20, "humidity_pct": 80}
                for k in range(5001)]
    assert _upload(client, field_id, too_many).status_code == 422
    assert _upload(client, field_id, [{"observed_at": start.isoformat(), "temp_c": 20, "humidity_pct": 101}]).status_code == 422
    assert _upload(client, field_id, _readings(start, 1, 20, 80), sensor="bad key").status_code == 422
    assert _upload(client, field_id, _readings(start, 1, 20, 80), device="no-such").status_code == 404
    assert _upload(client, 999, _readings(start, 1, 20, 80)).status_code == 404
    assert _upload(client, field_id, _readings(start, 1, 20, 80), device="gh-01").status_code == 200


def test_env_summary_metrics_and_missing_coverage(client):
    field_id = _setup(client)
    night = datetime(2026, 10, 1, 18, tzinfo=FIELD_TZ)
    _upload(client, field_id, _readings(night, 14, 16, 97))  # 一整夜湿润，但 72 小时只覆盖 14 小时
    env = client.get(f"{BASE}/fields/{field_id}/env").json()
    assert env["sensors"] == ["th-01"]
    day = next(d for d in env["daily"] if d["field_date"] == "2026-10-01")
    assert day["night_wet_hours"] == 14 and day["favorable_hours"] == 6
    assert env["index"]["env_index"] is None and env["index"]["coverage"] < 0.5
    assert env["morning_window"] is not None and env["morning_window"]["date"] == "2026-10-02"
    assert any(h["missing"] for h in env["hourly"]) and all(h["wet"] for h in env["hourly"] if not h["missing"])
    bad = client.get(f"{BASE}/fields/{field_id}/env", params={"since": "2026-10-02T00:00:00Z",
                                                               "until": "2026-10-01T00:00:00Z"})
    assert bad.status_code == 422


# ---------------------------------------------------------------- 每株状态与巡检计划


def _greenhouse(client):
    """两垄 × 5 株，10 月 1 日拍过一趟（叶背），R01-P003 叶背偏褐。"""
    field_id = _setup(client)
    client.post(f"{BASE}/fields/{field_id}/observation-units/bulk",
                json={"rows": [{"row_no": 1, "plants": 5, "spacing_m": 0.4}, {"row_no": 2, "plants": 5, "spacing_m": 0.4}]})
    points = []
    for row in (1, 2):
        for pos in range(1, 6):
            key = f"R{row:02d}-P{pos:03d}"
            if key == "R02-P005":
                continue  # 这株没拍到
            photo = BROWN if key == "R01-P003" else None
            seq = len(points)
            points.append(_point(seq, key, side="under", **({"photo": photo} if photo else {})))
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, points)).json()["patrol_id"]
    return field_id, patrol_id


def test_plant_states_prefer_human_label(client):
    field_id, patrol_id = _greenhouse(client)
    states = {s["key"]: s for s in client.get(f"{BASE}/fields/{field_id}/plant-states").json()}
    assert len(states) == 10
    assert states["R02-P005"]["state"] == "unknown" and states["R02-P005"]["last_seen_at"] is None
    assert states["R01-P001"]["source"] == "model" and states["R01-P001"]["confidence"] == 0.3
    point = next(p for p in client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"]
                 if p["observation_key"] == "R01-P001")
    assert client.post(f"{BASE}/capture-points/{point['id']}/annotations",
                       json={"label": "downy_mildew_early", "annotator_name": "王老师"}).status_code == 201
    states = {s["key"]: s for s in client.get(f"{BASE}/fields/{field_id}/plant-states").json()}
    assert (states["R01-P001"]["state"], states["R01-P001"]["source"]) == ("early", "human")


def test_patrol_plan_is_idempotent_and_latest_matches(client):
    field_id, _ = _greenhouse(client)
    body = {"plan_date": "2026-10-03", "created_by": "张工"}
    first = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json=body)
    assert first.status_code == 200, first.text
    plan = first.json()
    assert plan["plan_version"] == "planner-v0" and plan["units"] == 10
    assert plan["env"]["env_index"] is None and plan["env"]["env_missing"] is True  # 没有环境读数：按中值处理
    ids = sorted(item["task_id"] for name in ("confirm", "reshoot", "coverage", "random") for item in plan[name])
    assert len(ids) == len(set(ids)) > 0
    assert any(item["key"] == "R02-P005" for item in plan["coverage"] + plan["reshoot"])  # 从没拍到的必须入选
    reshoot = plan["reshoot"][0]
    assert reshoot["task_type"] == "revisit" and "parts" in reshoot["rationale"]

    again = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json=body).json()
    again_ids = sorted(item["task_id"] for name in ("confirm", "reshoot", "coverage", "random") for item in again[name])
    assert again_ids == ids
    tasks = client.get(f"{BASE}/revisit-tasks", params={"field_id": field_id}).json()
    assert len(tasks) == len(ids)
    task = next(t for t in tasks if t["id"] == reshoot["task_id"])
    params = task["parameters"]
    assert params["plan_date"] == "2026-10-03" and params["observation_key"] == reshoot["key"]
    assert [v["side"] for v in params["views"]] == ["under", "under", "under"]
    assert task["observation_unit_id"] == reshoot["unit_id"] and task["created_by"] == "张工"

    latest = client.get(f"{BASE}/fields/{field_id}/patrol-plans/latest").json()
    for name in ("confirm", "reshoot", "coverage", "random"):
        assert [i["task_id"] for i in latest[name]] == [i["task_id"] for i in again[name]], name
    assert latest["seed"] == plan["seed"] and latest["params"] is None


def test_regenerated_plan_supersedes_queued_tasks(client):
    field_id, patrol_id = _greenhouse(client)
    body = {"plan_date": "2026-10-03"}
    first = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json=body).json()
    assert [i["key"] for i in first["confirm"]] == ["R01-P003"] and first["generation"] == 1
    confirm_task = first["confirm"][0]["task_id"]
    # 人工确认为明显后重新生成：这株不再推确认，原确认任务作废，派车队列里只剩新计划的任务
    point = next(p for p in client.get(f"{BASE}/capture-points?patrol_id={patrol_id}").json()["items"]
                 if p["observation_key"] == "R01-P003")
    client.post(f"{BASE}/capture-points/{point['id']}/annotations",
                json={"label": "downy_mildew_symptomatic", "annotator_name": "王老师"})
    second = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json=body).json()
    assert second["confirm"] == [] and second["generation"] == 2
    lists = ("confirm", "reshoot", "coverage", "random")
    kept = {item["task_id"] for name in lists for item in second[name]}
    tasks = {t["id"]: t for t in client.get(f"{BASE}/revisit-tasks", params={"field_id": field_id}).json()}
    assert tasks[confirm_task]["status"] == "cancelled"
    assert tasks[confirm_task]["rationale"]["superseded_by"]["generation"] == 2
    assert {task_id for task_id, t in tasks.items() if t["status"] == "queued"} == kept
    latest = client.get(f"{BASE}/fields/{field_id}/patrol-plans/latest").json()
    assert latest["generation"] == 2
    for name in lists:  # 同一计划日重新生成：取最近计划时不能混进上一版的任务
        assert [i["task_id"] for i in latest[name]] == [i["task_id"] for i in second[name]], name


def test_wet_environment_lengthens_reshoot_and_gives_morning_window(client):
    field_id, _ = _greenhouse(client)
    # 计划日都取过去的日子（计划日晚于当前时间时环境只算到当前），9 月 25 日之前 72 小时干燥，9 月 28 日之前持续高湿
    _upload(client, field_id, _readings(datetime(2026, 9, 25, 8, tzinfo=FIELD_TZ) - timedelta(hours=72), 72, 22, 60))
    _upload(client, field_id, _readings(datetime(2026, 9, 28, 8, tzinfo=FIELD_TZ) - timedelta(hours=72), 72, 17, 97))
    dry = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json={"plan_date": "2026-09-25"}).json()
    wet = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json={"plan_date": "2026-09-28"}).json()
    assert dry["env"]["env_index"] == 0.0 and dry["window"] is None
    assert wet["env"]["env_index"] > 0.9 and wet["env"]["coverage"] == 1.0
    assert wet["reshoot_budget"] > dry["reshoot_budget"]
    assert wet["window"]["start"] == "05:30" and wet["window"]["date"] == "2026-09-28"
    assert wet["random"] or wet["coverage"]  # 风险高也保留抽查 / 全覆盖


def test_patrol_plan_rejects_bad_overrides(client):
    field_id, _ = _greenhouse(client)
    resp = client.post(f"{BASE}/fields/{field_id}/patrol-plans", json={"overrides": {"nope": 1}})
    assert resp.status_code == 422 and "未知" in resp.json()["detail"]
    assert client.get(f"{BASE}/fields/{field_id}/patrol-plans/latest").status_code == 404


def test_viewer_can_read_but_not_write(auth_env):
    client, session_factory = auth_env
    _add_user(session_factory, "op", "operator")
    _add_user(session_factory, "look", "viewer")
    op, viewer = _headers(client, "op"), _headers(client, "look")
    field_id = client.post(f"{BASE}/fields", json={"name": "权限棚", "boundary": BOUNDARY}, headers=op).json()["id"]
    reading = [{"observed_at": "2026-10-01T00:00:00Z", "temp_c": 20, "humidity_pct": 80}]
    assert client.post(f"{BASE}/fields/{field_id}/env-readings", json={"sensor_key": "th", "readings": reading},
                       headers=viewer).status_code == 403
    assert client.post(f"{BASE}/fields/{field_id}/env-readings", json={"sensor_key": "th", "readings": reading},
                       headers=op).status_code == 200
    assert client.post(f"{BASE}/fields/{field_id}/patrol-plans", json={}, headers=viewer).status_code == 403
    assert client.get(f"{BASE}/fields/{field_id}/env", headers=viewer).status_code == 200
    assert client.get(f"{BASE}/fields/{field_id}/plant-states", headers=viewer).status_code == 200
