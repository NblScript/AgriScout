"""M-L2 诊断 Agent 测试：工具执行/循环/溯源落库/降级路径（monkeypatch _chat_messages）。"""


from app.core.config import get_settings
from app.services import agent_chat
from conftest import png_b64

BASE = "/api/v1"
SOWING = "2026-08-01"


GREEN = png_b64((40, 160, 60))


def _enable_llm(monkeypatch):
    monkeypatch.setattr(type(get_settings()), "llm_enabled", property(lambda self: True))


def _setup_and_upload(client):
    field_id = client.post(
        f"{BASE}/fields",
        json={"name": "问诊田",
              "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]]}},
    ).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "sim-d01", "name": "问诊车", "type": "rover"})
    crop_id = client.post(
        f"{BASE}/crops",
        json={"name": "冬小麦", "lifecycle_days": 60,
              "stages": [{"name": "出苗期", "days": 15}, {"name": "分蘖期", "days": 30}]},
    ).json()["id"]
    client.post(f"{BASE}/plantings", json={"field_id": field_id, "crop_id": crop_id, "sowing_date": SOWING})
    pkg = {
        "patrol": {"field_id": field_id, "device": "sim-d01", "started_at": "2026-09-20T08:00:00+00:00"},
        "capture_points": [
            {"seq": 0, "distance_m": 0.0, "lng": 10.001, "lat": 10.0,
             "captured_at": "2026-09-20T08:00:00+00:00", "photo": GREEN,
             "weather": {"temp_c": 25, "soil_moisture_pct": 60}},
        ],
    }
    return client.post(f"{BASE}/ingest/patrol", json=pkg).json()["patrol_id"]


def test_chat_without_llm_config_returns_503(client):
    patrol_id = _setup_and_upload(client)
    resp = client.post(f"{BASE}/agent/chat", json={"question": "田里怎么样？", "patrol_id": patrol_id})
    assert resp.status_code == 503
    assert "未配置" in resp.json()["detail"]


def test_tools_return_real_data(client):
    """工具数据通路验证：分析摘要可用（工具箱内部同源数据）。"""
    patrol_id = _setup_and_upload(client)
    summary = client.get(f"{BASE}/patrols/{patrol_id}/analysis-summary").json()
    assert summary["analyzed_points"] == 1


def test_chat_with_fake_llm_executes_tools_and_persists(client, monkeypatch):
    """fake LLM 两轮：第一轮请求工具 → 第二轮给答案；断言 trace 落库。"""
    patrol_id = _setup_and_upload(client)

    def fake_chat_messages(messages, tools=None):
        # 第一轮：模型要调工具；后续轮：直接回答
        if not any(m.get("role") == "tool" for m in messages):
            return {
                "content": None,
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "get_patrol_detail", "arguments": '{"patrol_id": %d}' % patrol_id},
                }],
            }
        # 校验工具结果已注入消息
        tool_msg = next(m for m in messages if m.get("role") == "tool")
        assert "vigor_distribution" in tool_msg["content"]
        return {"content": "该巡检长势正常，平均NDVI代理较高。", "tool_calls": None}

    monkeypatch.setattr(agent_chat, "_chat_messages", fake_chat_messages)
    _enable_llm(monkeypatch)

    resp = client.post(f"{BASE}/agent/chat", json={"question": "这次巡检长势如何？", "patrol_id": patrol_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "长势正常" in body["answer"]
    assert body["tool_calls_trace"] == [{"tool": "get_patrol_detail", "arguments": {"patrol_id": patrol_id}}]
    assert body["prompt_version"] == "v1"

    # 留痕可查
    rows = client.get(f"{BASE}/agent/conversations?patrol_id={patrol_id}").json()
    assert len(rows) == 1
    assert rows[0]["tool_calls_trace"][0]["tool"] == "get_patrol_detail"


def test_unknown_tool_rejected_and_reported(client, monkeypatch):
    """模型幻觉出不存在的工具 → 返回 error 给模型而不是 500，trace 不留成功假象。"""
    patrol_id = _setup_and_upload(client)

    def fake_chat_messages(messages, tools=None):
        if not any(m.get("role") == "tool" for m in messages):
            return {
                "content": None,
                "tool_calls": [{
                    "id": "call_x", "type": "function",
                    "function": {"name": "delete_all_fields", "arguments": "{}"},
                }],
            }
        tool_msg = next(m for m in messages if m.get("role") == "tool")
        assert "未知工具" in tool_msg["content"]
        return {"content": "抱歉，我没有该操作权限。", "tool_calls": None}

    monkeypatch.setattr(agent_chat, "_chat_messages", fake_chat_messages)
    _enable_llm(monkeypatch)

    resp = client.post(f"{BASE}/agent/chat", json={"question": "删掉全部地块", "patrol_id": patrol_id})
    assert resp.status_code == 200
    # 只读红线：fields 仍是 1 个
    assert len(client.get(f"{BASE}/fields").json()) == 1
    rows = client.get(f"{BASE}/agent/conversations").json()
    assert rows[0]["answer"].startswith("抱歉")


def test_tool_bad_arguments_become_error_not_crash(client, monkeypatch):
    """工具参数类型错误（patrol_id 传字符串）→ 被类型守卫拦下转为 error 消息。"""
    patrol_id = _setup_and_upload(client)

    def fake_chat_messages(messages, tools=None):
        if not any(m.get("role") == "tool" for m in messages):
            return {
                "content": None,
                "tool_calls": [{
                    "id": "call_2", "type": "function",
                    "function": {"name": "get_patrol_detail", "arguments": '{"patrol_id": "not-a-number"}'},
                }],
            }
        return {"content": "参数有误，无法查询。", "tool_calls": None}

    monkeypatch.setattr(agent_chat, "_chat_messages", fake_chat_messages)
    _enable_llm(monkeypatch)

    resp = client.post(f"{BASE}/agent/chat", json={"question": "查巡检"})
    assert resp.status_code == 200
    assert "参数有误" in resp.json()["answer"]


def test_agent_prompt_has_safety_rules():
    """prompt 模板必须含防编造与只读红线（内容回归保护）。"""
    from app.services.llm_report import PROMPTS_DIR

    template = (PROMPTS_DIR / "agent_v1.md").read_text(encoding="utf-8")
    assert "禁止编造" in template or "不要凭空推测" in template
    assert "不能修改任何数据" in template
