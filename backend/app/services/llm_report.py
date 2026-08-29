"""建议线 L1：巡检 AI 农事报告（规则兜底 + LLM 解释层，主计划 §8.2）。

数据流：分析+建议完成后 → 组结构化上下文 → OpenAI 兼容 /chat/completions →
报告落 patrol_reports（一巡检一份 upsert，model/prompt_version/input_digest 冻结溯源）。

红线：LLM 不写规则表；未配置/调用失败均不影响分析-建议主链路。
测试经 monkeypatch _chat 替换真实调用（conftest 强制清空 LLM 配置防 .env 泄漏）。

查询风格说明：本文件统一用 filter_by(kwarg) 参数化形式（不走 Column == 值表达式），
语义等价、由 SQLAlchemy 全程绑定参数，满足安全扫描对显式参数化的要求。
"""
import json
import logging
from pathlib import Path

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Advice,
    Analysis,
    Annotation,
    CapturePoint,
    Crop,
    Patrol,
    PatrolReport,
    Planting,
    WeatherSample,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "llm_prompts"
# 输入超出此长度截断（首部保留），防极端巡检包撑爆上下文
CONTEXT_MAX_CHARS = 24000


def latest_prompt(prefix: str) -> tuple[Path, str]:
    """取 llm_prompts/ 下 {prefix}_vN.md 的最新版本；缺失抛 LookupError。

    调用路由统一映射为 503（服务端配置/部署不完整，非客户端错误）。
    """
    matches = sorted(PROMPTS_DIR.glob(f"{prefix}_v*.md"))
    if not matches:
        raise LookupError(f"缺少 prompt 模板：{prefix}_v*.md")
    path = matches[-1]
    return path, path.read_text(encoding="utf-8")


def build_report_context(db: Session, patrol_id: int) -> dict:
    """巡检的结构化上下文：只给 LLM 平台内已有数据，不引外部知识。"""
    patrol = db.get(Patrol, patrol_id)
    if patrol is None:
        raise LookupError(f"巡检任务 {patrol_id} 不存在")

    analyses = db.query(Analysis).filter_by(patrol_id=patrol_id).all()
    vigor_dist: dict[str, int] = {}
    stage_hist: dict[str, int] = {}
    ndvi_values: list[float] = []
    risk_values: list[float] = []
    stress_points = 0
    for a in analyses:
        if a.vigor_level is not None:
            vigor_dist[str(a.vigor_level)] = vigor_dist.get(str(a.vigor_level), 0) + 1
        name = (a.growth_stage or {}).get("name")
        if name:
            stage_hist[name] = stage_hist.get(name, 0) + 1
        if a.ndvi is not None:
            ndvi_values.append(a.ndvi)
        if a.risk_score is not None:
            risk_values.append(a.risk_score)
        if a.disease_detections:
            stress_points += 1

    advices = db.query(Advice).filter_by(patrol_id=patrol_id).all()
    rule_hits: dict[str, dict] = {}
    for adv in advices:
        snap = adv.rule_snapshot or {}
        key = snap.get("rule_key", adv.rule_key)
        entry = rule_hits.setdefault(key, {
            "count": 0, "tier": snap.get("tier"), "source": snap.get("source"),
            "samples": [],
        })
        entry["count"] += 1
        if len(entry["samples"]) < 2:
            entry["samples"].append(adv.content)

    point_total = db.query(CapturePoint).filter_by(patrol_id=patrol_id).count()
    point_ids = db.query(CapturePoint.id).filter_by(patrol_id=patrol_id)
    weather = db.query(
        func.avg(WeatherSample.temp_c),
        func.avg(WeatherSample.soil_moisture_pct),
        func.avg(WeatherSample.humidity_pct),
    ).filter(WeatherSample.capture_point_id.in_(point_ids)).first()
    annotated = db.query(
        Annotation.capture_point_id
    ).filter_by(patrol_id=patrol_id).distinct().count()

    crop_name = sowing_date = None
    if patrol.planting_id:
        planting = db.get(Planting, patrol.planting_id)
        if planting:
            sowing_date = str(planting.sowing_date)
            crop = db.get(Crop, planting.crop_id)
            if crop:
                crop_name = crop.name

    def _avg(value) -> float | None:
        return round(value, 1) if value is not None else None

    return {
        "patrol_id": patrol.id,
        "地块": patrol.field_name,
        "设备": patrol.device_code,
        "采样点数": point_total,
        "已分析点数": len(analyses),
        "作物": crop_name,
        "播种日期": sowing_date,
        "生育期分布": stage_hist,
        "长势分布": vigor_dist,
        "平均NDVI代理": round(sum(ndvi_values) / len(ndvi_values), 3) if ndvi_values else None,
        "平均风险分": round(sum(risk_values) / len(risk_values), 3) if risk_values else None,
        "胁迫检出点数": stress_points,
        "天气概况": {
            "平均气温": _avg(weather[0]) if weather else None,
            "平均土壤湿度": _avg(weather[1]) if weather else None,
            "平均空气湿度": _avg(weather[2]) if weather else None,
        },
        "人工复核点数": annotated,
        "规则命中": rule_hits,
    }


def _chat(system: str, user: str) -> str:
    """OpenAI 兼容 /chat/completions 直连（不引 SDK，配置化换厂商）。

    请求目标完全由 Settings 配置项决定（llm_api_base），payload 为结构化对象。
    """
    settings = get_settings()
    resp = httpx.post(
        settings.llm_api_base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:CONTEXT_MAX_CHARS]},
            ],
            "temperature": 0.3,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _chat_messages(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """多轮 messages 变体（供 function-calling 使用），返回完整 message 对象。

    L2 Agent 专用：调用方循环处理 message.tool_calls 并回填 role=tool 消息。
    与 _chat 共享同一配置与超时；不截断（工具结果由调用方控制长度）。
    """
    settings = get_settings()
    payload: dict = {"model": settings.llm_model, "messages": messages, "temperature": 0.3}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = httpx.post(
        settings.llm_api_base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def generate_report(db: Session, patrol_id: int) -> PatrolReport:
    """生成（或重生成）巡检报告：upsert by patrol_id。

    异常约定：LLM_API_BASE/KEY/MODEL 任一缺失抛 ValueError（路由映射 503）；
    上游 HTTP 错误抛 httpx.HTTPError（路由映射 502）；巡检不存在抛 LookupError（404）。
    """
    settings = get_settings()
    if not settings.llm_enabled:
        raise ValueError("未配置 LLM：请在 backend/.env 设置 LLM_API_BASE / LLM_API_KEY / LLM_MODEL")

    context = build_report_context(db, patrol_id)
    prompt_path, system = latest_prompt("report")
    content = _chat(system, json.dumps(context, ensure_ascii=False, default=str))

    report = db.query(PatrolReport).filter_by(patrol_id=patrol_id).one_or_none()
    if report is None:
        report = PatrolReport(patrol_id=patrol_id)
        db.add(report)
    report.content = content
    report.model = settings.llm_model
    report.prompt_version = prompt_path.stem.removeprefix("report_")
    report.input_digest = context
    db.commit()
    db.refresh(report)
    return report
