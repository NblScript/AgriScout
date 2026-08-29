"""M-L1 规则起草 Agent 测试：燃料统计/起草解析/影子 diff/审批流转（monkeypatch _chat）。"""


from app.core.config import get_settings
from app.services import agent_rule_draft
from conftest import png_b64

BASE = "/api/v1"
SOWING = "2026-08-01"
FAKE_DRAFTS = """```json
[
  {
    "action": "modify",
    "rule_key": "R-TEST-ROUTINE",
    "draft": {
      "rule_key": "R-TEST-ROUTINE", "tier": "routine", "priority": "low",
      "condition": {"stage": "拔节期"},
      "action": "拔节期常规管理（按反馈修订版）。", "source": "基于平台反馈统计，待农技复核"
    },
    "reason": "驳回率偏高，收窄保底范围"
  }
]
```"""


GREEN = png_b64((40, 160, 60))


def _enable_llm(monkeypatch):
    monkeypatch.setattr(type(get_settings()), "llm_enabled", property(lambda self: True))


def test_shadow_run_does_not_mutate_rules(client, monkeypatch):
    """P0 回归：影子运行绝不能改规则表/建议表（savepoint 击穿事故的守卫）。"""
    field_id, patrol_id = _setup(client)
    rules_before = {
        r["rule_key"]: (r["version"], r["condition"], r["active"])
        for r in client.get(f"{BASE}/rules").json()
    }
    advices_before = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["total"]

    # 不走 LLM：手工造一条 modify 修订案（阈值改到不可能命中的 999）
    from app.core.db import get_session_factory
    from app.main import app
    from app.models import RuleRevision

    # 取 conftest 覆盖后的 TestSession（写测试内存库），不能用真实 SessionLocal
    TestSessionFactory = app.dependency_overrides[get_session_factory]()
    db = TestSessionFactory()
    rev = RuleRevision(
        rule_key="R-TEST-ROUTINE",
        action="modify",
        draft={"rule_key": "R-TEST-ROUTINE", "tier": "routine", "priority": "low",
               "condition": {"stage": "不存在的生育期"}, "action": "影子实验文案", "source": "影子测试"},
        reason="P0 回归测试",
        model="fake", prompt_version="v1",
    )
    db.add(rev)
    db.commit()
    rev_id = rev.id
    db.close()

    shadow = client.post(f"{BASE}/rule-revisions/{rev_id}/shadow?sample_size=1")
    assert shadow.status_code == 200, shadow.text

    # 规则表逐字段不变
    rules_after = {
        r["rule_key"]: (r["version"], r["condition"], r["active"])
        for r in client.get(f"{BASE}/rules").json()
    }
    assert rules_after == rules_before, "影子运行改写了规则表！"

    # 建议表 suggested 总数不变（被影子重算过的痕迹检查）
    advices_after = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["total"]
    assert advices_after == advices_before

    # 且 diff 报告正常产出（stage 不存在 → after 应为 0 命中）
    sr = shadow.json()["shadow_result"]
    assert sr["per_patrol"][0]["after"] == 0


def _setup(client, with_advice_flow=True):
    field_id = client.post(
        f"{BASE}/fields",
        json={"name": "起草测试田",
              "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]}},
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-d01", "name": "起草车", "type": "rover"})
    crop_id = client.post(
        f"{BASE}/crops",
        json={"name": "冬小麦", "lifecycle_days": 60,
              "stages": [{"name": "出苗期", "days": 15}, {"name": "分蘖期", "days": 30},
                          {"name": "拔节期", "days": 15}]},
    ).json()["id"]
    client.post(f"{BASE}/plantings", json={"field_id": field_id, "crop_id": crop_id, "sowing_date": SOWING})
    # 一条常规规则（起草目标）
    client.post(
        f"{BASE}/rules",
        json={"rule_key": "R-TEST-ROUTINE", "tier": "routine", "priority": "low",
              "condition": {}, "action": "常规巡检保底建议。", "source": "测试"},
    )
    if not with_advice_flow:
        return field_id
    pkg = {
        "patrol": {"field_id": field_id, "device": "sim-d01", "started_at": "2026-09-20T08:00:00+00:00"},
        "capture_points": [
            {"seq": 0, "distance_m": 0.0, "lng": 10.001, "lat": 10.0,
             "captured_at": "2026-09-20T08:00:00+00:00", "photo": GREEN,
             "weather": {"temp_c": 25, "soil_moisture_pct": 60}},
        ],
    }
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=pkg).json()["patrol_id"]
    # 人工决策：驳回一条建议（制造燃料）
    advices = client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["items"]
    if advices:
        client.patch(f"{BASE}/advices/{advices[0]['id']}", json={"status": "rejected"})
    return field_id, patrol_id


def test_generate_without_llm_returns_503(client):
    _setup(client)
    resp = client.post(f"{BASE}/rule-revisions/generate")
    assert resp.status_code == 503


def test_feedback_collects_reject_signal(client):
    _setup(client)
    fb = client.get(f"{BASE}/rule-feedback").json()
    assert fb["global"]["total_advices"] >= 1
    assert fb["global"]["rejected"] if "rejected" in fb["global"] else True
    routine = next((r for r in fb["rules"] if r["rule_key"] == "R-TEST-ROUTINE"), None)
    assert routine is not None
    assert routine["rejected"] == 1
    assert routine["reject_rate"] == 1.0


def test_draft_parse_and_persist(client, monkeypatch):
    field_id, _ = _setup(client)
    monkeypatch.setattr(agent_rule_draft, "_chat", lambda system, user: FAKE_DRAFTS)
    _enable_llm(monkeypatch)

    resp = client.post(f"{BASE}/rule-revisions/generate")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1

    revisions = client.get(f"{BASE}/rule-revisions?status=draft").json()
    assert len(revisions) == 1
    rev = revisions[0]
    assert rev["rule_key"] == "R-TEST-ROUTINE"
    assert rev["action"] == "modify"
    assert rev["draft"]["condition"] == {"stage": "拔节期"}
    assert "驳回率" in rev["reason"]


def test_shadow_run_and_approve_updates_rule_version(client, monkeypatch):
    field_id, patrol_id = _setup(client)
    monkeypatch.setattr(agent_rule_draft, "_chat", lambda system, user: FAKE_DRAFTS)
    _enable_llm(monkeypatch)
    client.post(f"{BASE}/rule-revisions/generate")
    rev = client.get(f"{BASE}/rule-revisions?status=draft").json()[0]

    # 未影子运行就批准 → 422
    early = client.post(f"{BASE}/rule-revisions/{rev['id']}/approve",
                        json={"decided_by": "测试员"})
    assert early.status_code == 422

    # 影子运行 → diff 落库
    shadow = client.post(f"{BASE}/rule-revisions/{rev['id']}/shadow?sample_size=1")
    assert shadow.status_code == 200, shadow.text
    sr = shadow.json()["shadow_result"]
    assert sr["patrols_checked"] == [patrol_id]
    assert "before" in sr["per_patrol"][0]

    # 批准 → 规则 version+1 且内容更新
    approve = client.post(f"{BASE}/rule-revisions/{rev['id']}/approve",
                          json={"decided_by": "测试员", "note": "同意收窄"})
    assert approve.status_code == 200, approve.text
    assert approve.json()["applied_version"] == 2

    rules = client.get(f"{BASE}/rules").json()
    rule = next(r for r in rules if r["rule_key"] == "R-TEST-ROUTINE")
    assert rule["version"] == 2
    assert rule["condition"] == {"stage": "拔节期"}

    # 已决策的不能再批
    again = client.post(f"{BASE}/rule-revisions/{rev['id']}/approve", json={"decided_by": "x"})
    assert again.status_code == 422


def test_reject_archives_without_touching_rules(client, monkeypatch):
    _setup(client)
    monkeypatch.setattr(agent_rule_draft, "_chat", lambda system, user: FAKE_DRAFTS)
    _enable_llm(monkeypatch)
    client.post(f"{BASE}/rule-revisions/generate")
    rev = client.get(f"{BASE}/rule-revisions?status=draft").json()[0]

    before = next(r for r in client.get(f"{BASE}/rules").json() if r["rule_key"] == "R-TEST-ROUTINE")
    rejected = client.post(f"{BASE}/rule-revisions/{rev['id']}/reject",
                           json={"decided_by": "测试员", "note": "依据不足"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    after = next(r for r in client.get(f"{BASE}/rules").json() if r["rule_key"] == "R-TEST-ROUTINE")
    assert after["version"] == before["version"]  # 驳回不动规则表


def test_malformed_llm_output_creates_nothing(client, monkeypatch):
    """LLM 输出乱码 → 宁缺勿滥，0 修订案落库。"""
    _setup(client, with_advice_flow=False)
    monkeypatch.setattr(agent_rule_draft, "_chat", lambda system, user: "我觉得规则挺好的不用改。")
    _enable_llm(monkeypatch)
    resp = client.post(f"{BASE}/rule-revisions/generate")
    assert resp.status_code == 200
    assert resp.json()["created"] == 0
