"""建议线 L2：对话式诊断 Agent（主计划 §8.2）。

function-calling 循环 + 只读工具箱（agent_tools.py）。红线：只读不写——
工具全为 SELECT 查询；每轮工具调用记录入 trace，问答与调用链落库可溯源。
"""
import json
import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.agent_tools import safe_dispatch
from app.services.llm_report import _chat_messages, latest_prompt

logger = logging.getLogger(__name__)

# 工具调用轮次上限：防失控循环；正常诊断 1-3 轮足够
MAX_TOOL_ROUNDS = 5
# 单次工具结果注入 messages 的最大字符数
TOOL_RESULT_MAX_CHARS = 6000
# 单轮最多工具调用数
MAX_CALLS_PER_ROUND = 4


def _register(name: str, description: str, parameters: dict):
    """装饰器：把工具函数注册进 TOOLS，并生成 OpenAI tools schema。"""
    def wrap(fn):
        TOOLS[name] = (fn, {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
        })
        return fn
    return wrap


# 延迟导入避免循环依赖；注册表在模块加载时填充
from app.services.agent_tools import (  # noqa: E402
    tool_get_advices,
    tool_get_annotations,
    tool_get_field_overview,
    tool_get_patrol_detail,
    tool_get_platform_stats,
    tool_get_point_samples,
)

TOOLS: dict[str, tuple] = {}

_register("get_field_overview", "获取全部地块、在种作物与设备总览", {"type": "object", "properties": {}})(tool_get_field_overview)
_register("get_patrol_detail", "获取指定巡检的详情与分析摘要（长势/风险/生育期分布）", {
    "type": "object",
    "properties": {"patrol_id": {"type": "integer", "description": "巡检 ID"}},
    "required": ["patrol_id"],
})(tool_get_patrol_detail)
_register("get_point_samples", "按长势/风险筛采样点（返回风险最高的 N 个）", {
    "type": "object",
    "properties": {
        "patrol_id": {"type": "integer"},
        "vigor_level": {"type": "integer", "description": "1-5，可选"},
        "risk_min": {"type": "number", "description": "最低风险分 0-1，可选"},
        "limit": {"type": "integer", "description": "默认 10"},
    },
    "required": ["patrol_id"],
})(tool_get_point_samples)
_register("get_advices", "查询巡检的农事建议（含规则出处）", {
    "type": "object",
    "properties": {
        "patrol_id": {"type": "integer"},
        "status": {"type": "string", "enum": ["suggested", "accepted", "rejected"]},
        "limit": {"type": "integer"},
    },
    "required": ["patrol_id"],
})(tool_get_advices)
_register("get_annotations", "查询人工复核标注", {
    "type": "object",
    "properties": {
        "patrol_id": {"type": "integer", "description": "可选，不传查全部"},
        "limit": {"type": "integer"},
    },
})(tool_get_annotations)
_register("get_platform_stats", "平台全局统计（地块/巡检/建议规模）", {"type": "object", "properties": {}})(tool_get_platform_stats)

TOOL_SCHEMAS = [schema for _, schema in TOOLS.values()]


def _execute_tool(db: Session, name: str, arguments: dict) -> dict:
    """白名单分发执行；任何异常转为 error 字段返回模型，不外抛。"""
    entry = TOOLS.get(name)
    if entry is None:
        return {"error": f"未知工具 {name}"}
    try:
        return safe_dispatch(db, entry[0], arguments)
    except TypeError as e:
        return {"error": f"参数不匹配：{e}"}
    except Exception as e:  # noqa: BLE001 工具失败转为模型可读信息
        return {"error": f"工具执行失败：{e}"}


def chat(db: Session, question: str, patrol_id: int | None = None) -> dict:
    """诊断问答主入口：function-calling 循环 + 溯源 trace。

    返回 {"answer", "tool_calls_trace", "model", "prompt_version"}；
    LLM 未配置抛 ValueError（路由→503），上游错误抛 httpx.HTTPError（→502）。
    """
    settings = get_settings()
    if not settings.llm_enabled:
        raise ValueError("未配置 LLM：请在 backend/.env 设置 LLM_API_BASE / LLM_API_KEY / LLM_MODEL")

    prompt_path, system = latest_prompt("agent")

    context_note = f"\n\n用户当前正在查看巡检 #{patrol_id}，可作为默认分析对象。" if patrol_id else ""
    messages: list[dict] = [
        {"role": "system", "content": system + context_note},
        {"role": "user", "content": question[:4000]},
    ]

    trace: list[dict] = []
    message: dict = {}
    for _ in range(MAX_TOOL_ROUNDS):
        message = _chat_messages(messages, TOOL_SCHEMAS)
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            break
        messages.append(message)  # assistant 的 tool_calls 消息原样回填
        executed_calls = tool_calls[:MAX_CALLS_PER_ROUND]
        for call in executed_calls:
            name = call["function"]["name"]
            raw = call["function"].get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                arguments = {}
            result = _execute_tool(db, name, arguments)
            trace.append({"tool": name, "arguments": arguments})
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False, default=str)[:TOOL_RESULT_MAX_CHARS],
            })
        # 被截断的调用也必须补 tool 消息（否则 assistant 消息与 tool 消息
        # 数量不配对，上游 API 返回 400）
        for call in tool_calls[MAX_CALLS_PER_ROUND:]:
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": json.dumps({"error": "单轮工具调用超出上限，未执行"}) ,
            })

    answer = message.get("content") or ""
    if not answer:
        # 轮次耗尽仍无正文：去掉工具消息，强制收束一轮
        trimmed = [m for m in messages if m.get("role") != "tool"]
        trimmed.append({"role": "user", "content": "工具调用已达上限，请基于已有信息直接回答。"})
        answer = _chat_messages(trimmed).get("content") or ""

    return {
        "answer": answer,
        "tool_calls_trace": trace,
        "model": settings.llm_model,
        "prompt_version": prompt_path.stem.removeprefix("agent_"),
    }
