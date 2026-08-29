"""M-L1 巡检 AI 报告测试：未配置降级/落库溯源/upsert 幂等/上下文完整性。

真实 LLM 调用经 monkeypatch _chat 替换；conftest 已强制清空 LLM 环境变量，
保证 runner 主链路在本测试外恒走"未配置→静默跳过"路径。
"""

import pytest

from app.core.config import get_settings
from app.services import llm_report
from conftest import png_b64

BASE = "/api/v1"
SOWING = "2026-08-01"
FAKE_REPORT = (
    "## 总体判断\n麦苗整体长势正常。\n"
    "## 风险提示\n未见显著风险。\n"
    "## 行动清单\n- 保持现有水肥管理\n"
    "## 数据依据\n- 平均NDVI代理 1.0\n"
)


GREEN = png_b64((40, 160, 60))


def _setup_and_upload(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={
            "name": "报告测试田",
            "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]},
        },
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-d01", "name": "报告测试车", "type": "rover"})
    crop_id = client.post(
        f"{BASE}/crops",
        json={
            "name": "冬小麦", "lifecycle_days": 60,
            "stages": [{"name": "出苗期", "days": 15}, {"name": "分蘖期", "days": 30}],
        },
    ).json()["id"]
    client.post(
        f"{BASE}/plantings", json={"field_id": field_id, "crop_id": crop_id, "sowing_date": SOWING}
    )
    client.post(
        f"{BASE}/rules",
        json={
            "rule_key": "R-REPORT-ROUTINE", "tier": "routine", "priority": "low",
            "condition": {}, "action": "常规巡检保底建议。", "source": "测试出处",
        },
    )
    pkg = {
        "patrol": {"field_id": field_id, "device": "sim-d01",
                   "started_at": "2026-09-20T08:00:00+00:00"},
        "capture_points": [
            {"seq": 0, "distance_m": 0.0, "lng": 10.001, "lat": 10.0,
             "captured_at": "2026-09-20T08:00:00+00:00", "photo": GREEN,
             "weather": {"temp_c": 25, "soil_moisture_pct": 60}},
        ],
    }
    return client.post(f"{BASE}/ingest/patrol", json=pkg).json()["patrol_id"]


def _enable_llm(monkeypatch):
    """conftest 已清空 LLM 配置（防泄漏）；需要 LLM 的用例在此安全地打开开关。"""
    monkeypatch.setattr(type(get_settings()), "llm_enabled", property(lambda self: True))


def test_generate_without_llm_config_returns_503(client):
    """未配置 LLM：手动生成 → 503，且分析-建议主链路不受影响。"""
    patrol_id = _setup_and_upload(client)
    assert client.get(f"{BASE}/patrols/{patrol_id}/report").status_code == 404
    resp = client.post(f"{BASE}/patrols/{patrol_id}/report/generate")
    assert resp.status_code == 503
    assert "未配置" in resp.json()["detail"]
    # 主链路完好：分析 1 点 + 常规建议已生成
    summary = client.get(f"{BASE}/patrols/{patrol_id}/analysis-summary").json()
    assert summary["analyzed_points"] == 1
    assert len(client.get(f"{BASE}/patrols/{patrol_id}/advices").json()["items"]) >= 1


def test_generate_upsert_and_get_with_fake_llm(client, monkeypatch):
    """fake LLM：报告落库可查、快照字段完整、重生成 upsert 不插重。"""
    patrol_id = _setup_and_upload(client)
    monkeypatch.setattr(llm_report, "_chat", lambda system, user: FAKE_REPORT)
    _enable_llm(monkeypatch)

    first = client.post(f"{BASE}/patrols/{patrol_id}/report/generate")
    assert first.status_code == 200, first.text
    assert first.json()["prompt_version"] == "v1"

    got = client.get(f"{BASE}/patrols/{patrol_id}/report")
    assert got.status_code == 200
    report = got.json()
    assert "## 总体判断" in report["content"]
    assert report["input_digest"]["作物"] == "冬小麦"
    assert report["input_digest"]["已分析点数"] == 1
    assert "R-REPORT-ROUTINE" in report["input_digest"]["规则命中"]
    assert report["input_digest"]["规则命中"]["R-REPORT-ROUTINE"]["source"] == "测试出处"

    # 重生成：同 patrol 仍只有一份（unique upsert）
    again = client.post(f"{BASE}/patrols/{patrol_id}/report/generate")
    assert again.status_code == 200
    reports = client.get(f"{BASE}/patrols/{patrol_id}/report").json()
    assert again.json()["report_id"] == reports["id"]


def test_context_contains_numeric_evidence(client, monkeypatch):
    """prompt 上下文必须携带关键数值（防 LLM 编造的底线：喂给它真实数）。"""
    patrol_id = _setup_and_upload(client)
    captured = {}
    monkeypatch.setattr(llm_report, "_chat", lambda system, user: captured.update(user=user) or FAKE_REPORT)
    _enable_llm(monkeypatch)
    resp = client.post(f"{BASE}/patrols/{patrol_id}/report/generate")
    assert resp.status_code == 200
    import json as _json
    ctx = _json.loads(captured["user"])
    assert ctx["采样点数"] == 1 and ctx["已分析点数"] == 1
    assert ctx["平均NDVI代理"] is not None
    assert ctx["天气概况"]["平均气温"] == 25.0


def test_patrol_not_found_404(client, monkeypatch):
    monkeypatch.setattr(llm_report, "_chat", lambda system, user: FAKE_REPORT)
    _enable_llm(monkeypatch)
    resp = client.post(f"{BASE}/patrols/99999/report/generate")
    assert resp.status_code == 404


def test_prompt_template_requires_evidence_citation():
    """prompt 模板必须包含防编造与溯源约束（内容回归保护）。"""
    template = (llm_report.PROMPTS_DIR / "report_v1.md").read_text(encoding="utf-8")
    assert "禁止编造" in template
    assert "出处" in template
    assert "NDVI 代理" in template
