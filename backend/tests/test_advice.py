"""M4 建议引擎测试：规则CRUD/YAML同步/匹配生成/快照冻结/人工决策保护。"""
import base64
import io

from PIL import Image

BASE = "/api/v1"
# 生育期表：出苗15+分蘖30 → 第45-59天为拔节期；播种2026-08-01，拍摄2026-09-20=第50天
SOWING = "2026-08-01"


def _png_b64(rgb: tuple[int, int, int]) -> str:
    img = Image.new("RGB", (24, 24), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


BROWN = _png_b64((120, 85, 50))  # 枯黄胁迫 + 低长势
GREEN = _png_b64((40, 160, 60))  # 茂密植被


def _setup(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={
            "name": "建议测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-d01", "name": "建议测试车", "type": "rover"})
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
    planting_id = client.post(
        f"{BASE}/plantings",
        json={"field_id": field_id, "crop_id": crop_id, "sowing_date": SOWING},
    ).json()["id"]
    return field_id, crop_id, planting_id


def _create_rules(client, crop_id):
    rules = [
        {
            "rule_key": "R-TEST-DROUGHT-JOINTING",
            "crop_id": crop_id,
            "tier": "threshold",
            "priority": "high",
            "condition": {
                "stage": "拔节期",
                "weather": {"soil_moisture_pct": {"lt": 55}},
            },
            "action": "{stage}遇旱（土壤湿度{soil_moisture_pct}%），建议3日内浇拔节水40–50方/亩。",
            "source": "测试规则·节水灌溉规程",
        },
        {
            "rule_key": "R-TEST-STRESS",
            "tier": "status",
            "priority": "high",
            "condition": {"stress_detected": True},
            "action": "检出叶色异常，请到 seq={seq} 点位实地复核并标注回流。",
            "source": "项目设计·复核闭环",
        },
        {
            "rule_key": "R-TEST-ROUTINE-JOINTING",
            "tier": "routine",
            "priority": "low",
            "condition": {},
            "action": "{stage}常规管理：氮肥后移追拔节肥。",
            "source": "测试规则·栽培学",
        },
    ]
    ids = {}
    for r in rules:
        resp = client.post(f"{BASE}/rules", json=r)
        assert resp.status_code == 201, resp.text
        ids[r["rule_key"]] = resp.json()["id"]
    return ids, rules


def _upload(client, field_id):
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
    return client.post(f"{BASE}/ingest/patrol", json=pkg)


def test_full_advice_flow_with_snapshot(client):
    field_id, crop_id, planting_id = _setup(client)
    _create_rules(client, crop_id)
    resp = _upload(client, field_id)
    assert resp.status_code == 201
    patrol_id = resp.json()["patrol_id"]

    # 分析完成 → 建议自动生成（阶段⑥）
    items = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["items"]
    assert len(items) == 4  # seq0 三条 + seq1 常规一条
    assert all(a["status"] == "suggested" for a in items)

    # 干旱+枯黄点(seq0)：干旱(high)+胁迫(high)+常规保底(low)，共三条
    seq0 = [a for a in items if a["rule_key"] != "R-TEST-ROUTINE-JOINTING" or a["capture_point_id"]]
    seq0_keys = {a["rule_key"] for a in seq0 if a["content"].startswith(("拔节期遇旱", "检出叶色异常"))}
    assert {"R-TEST-DROUGHT-JOINTING", "R-TEST-STRESS"} <= seq0_keys

    # 快照冻结：包含出处与版本，内容插值了观测值 40%
    drought = next(a for a in items if a["rule_key"] == "R-TEST-DROUGHT-JOINTING")
    snap = drought["rule_snapshot"]
    assert snap["version"] == 1 and snap["source"] == "测试规则·节水灌溉规程"
    assert snap["tier"] == "threshold" and snap["priority"] == "high"
    assert "土壤湿度40" in drought["content"]  # 命中观测值已插入文案
    assert "40–50方/亩" in drought["content"]

    # 绿色湿润点(seq1)：只有常规保底一条
    green_points = [a for a in items if a["content"].startswith("拔节期常规管理")]
    assert len(green_points) >= 1

    # 巡检摘要仍可用
    summary = client.get(f"{BASE}/patrols/{patrol_id}/analysis-summary").json()
    assert summary["analyzed_points"] == 2


def test_human_decisions_survive_regeneration(client):
    field_id, crop_id, planting_id = _setup(client)
    _, rules_meta = _create_rules(client, crop_id)
    patrol_id = _upload(client, field_id).json()["patrol_id"]

    items = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["items"]
    drought = next(a for a in items if a["rule_key"] == "R-TEST-DROUGHT-JOINTING")
    stress = next(a for a in items if a["rule_key"] == "R-TEST-STRESS")

    # 采纳干旱建议、驳回胁迫建议
    assert client.patch(f"{BASE}/advices/{drought['id']}", json={"status": "accepted"}).json()["status"] == "accepted"
    assert client.patch(f"{BASE}/advices/{stress['id']}", json={"status": "rejected"}).json()["status"] == "rejected"

    # 重生成：决策保留；被驳回的组合不再重复建议
    regen = client.post(f"{BASE}/patrols/{patrol_id}/advices/generate")
    assert regen.status_code == 200
    stats = regen.json()
    # 两条已决策的命中都被跳过重建：accepted 与 rejected 各一条
    assert stats["skipped_decided"] == 2

    after = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["items"]
    statuses = {(a["capture_point_id"], a["rule_key"]): a["status"] for a in after}
    pair_drought = (drought["capture_point_id"], "R-TEST-DROUGHT-JOINTING")
    pair_stress = (stress["capture_point_id"], "R-TEST-STRESS")
    assert statuses[pair_drought] == "accepted"          # 决策未被覆盖
    assert statuses[pair_stress] == "rejected"           # 驳回记录保留为事实
    # 且驳回的组合没有再产生新的 suggested 行（每对组合仅一行）
    stress_rows = [a for a in after if a["rule_key"] == "R-TEST-STRESS"]
    assert len(stress_rows) == 1 and stress_rows[0]["status"] == "rejected"
    assert len(after) == len({(a["capture_point_id"], a["rule_key"]) for a in after})


def test_rule_crud_version_and_soft_delete(client):
    _, crop_id, _ = _setup(client)
    rule = {
        "rule_key": "R-CRUD-CASE",
        "tier": "threshold",
        "priority": "medium",
        "condition": {"ndvi": {"lt": 0.2}},
        "action": "覆盖偏低{ndvi}",
        "source": "测试",
    }
    rid = client.post(f"{BASE}/rules", json=rule).json()["id"]

    # 重复 key → 409
    dup = client.post(f"{BASE}/rules", json=rule)
    assert dup.status_code == 409

    # 内容变更 → 版本自增；active 开关不升版本
    v1 = client.patch(f"{BASE}/rules/{rid}", json={"active": False}).json()
    assert v1["version"] == 1 and v1["active"] is False
    v2 = client.patch(f"{BASE}/rules/{rid}", json={"priority": "high", "active": True}).json()
    assert v2["version"] == 2 and v2["priority"] == "high"

    # 删除=软下线，行仍在且 active=False
    deleted = client.delete(f"{BASE}/rules/{rid}")
    assert deleted.json()["active"] is False
    assert client.get(f"{BASE}/rules?active=true").json() == []

    # 非法条件键 / routine 层带条件 → 422
    bad_key = {**rule, "rule_key": "R-BAD-KEY", "condition": {"foo": {"lt": 1}}}
    assert client.post(f"{BASE}/rules", json=bad_key).status_code == 422
    bad_tier = {**rule, "rule_key": "R-BAD-TIER", "tier": "routine", "condition": {"ndvi": {"lt": 1}}}
    assert client.post(f"{BASE}/rules", json=bad_tier).status_code == 422


def test_yaml_seed_sync_and_idempotency(client):
    # 真实种子库整体可导入且幂等（两次同步 created→unchanged）
    first = client.post(f"{BASE}/rules/sync-yaml").json()
    assert first["errors"] == [], first["errors"]
    assert first["created"] >= 18
    second = client.post(f"{BASE}/rules/sync-yaml").json()
    assert second["created"] == 0 and second["updated"] == 0
    assert second["unchanged"] == first["created"]

    listed = client.get(f"{BASE}/rules").json()
    keys = [r["rule_key"] for r in listed]
    assert len(keys) == len(set(keys))
    assert all(r["source"] for r in listed)  # 全部带出处（答辩溯源要求）


def test_generate_without_analysis_is_safe(client):
    """无分析数据时生成不崩溃：仅常规层命中（无条件规则恒真）。"""
    field_id, crop_id, _ = _setup(client)
    _create_rules(client, crop_id)
    # 手工建巡检包但照片不可读 → 无 analysis → 仅 routine 层命中
    pkg = {
        "patrol": {"field_id": field_id, "device": "sim-d01",
                   "started_at": "2026-09-21T08:00:00Z"},
        "capture_points": [
            {"seq": 0, "distance_m": 0, "lng": 10.001, "lat": 10.0,
             "captured_at": "2026-09-21T08:00:00+00:00",
             "photo": "/media/ghost.jpg", "weather": {"temp_c": 30}}],
    }
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=pkg).json()["patrol_id"]
    advices = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()
    # threshold/status 层因缺数据不命中，仅 routine 无条件恒命中
    keys = {a["rule_snapshot"]["tier"] for a in advices["items"]}
    assert keys == {"routine"}
