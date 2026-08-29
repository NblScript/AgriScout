"""建议引擎：规则匹配 → Advice 落库（带 rule_snapshot 冻结）。

设计要点（docs/05「规则引擎生命周期」）：
- 条件 all-of 语义，六类条件 × 六算子；引用的数据缺失视为不命中；
- 三层规则：threshold(天气) / status(分析) / routine(生育期保底)；
- 每点按优先级取 Top3——命中再多也不刷屏，无高优命中时常规层兜底；
- Advice 冻结 rule_snapshot，规则改版后历史建议仍可解释；
- 重生成幂等：只清理 suggested，人工已采纳/驳回的决策是事实，永不覆盖。
"""
import string
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models import Advice, Analysis, CapturePoint, Patrol, Planting, Rule, WeatherSample
from app.services.analysis.base import CaptureContext, calendar_growth_stage

TOP_K_PER_POINT = 3
_PRIORITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_WEATHER_FIELDS = {
    "temp_c", "humidity_pct", "light_lux",
    "wind_mps", "rain_mm", "soil_temp_c", "soil_moisture_pct",
}


# ---------- 点上下文 ----------


@dataclass(slots=True)
class PointContext:
    seq: int
    stage_name: str | None = None
    vigor_level: int | None = None
    ndvi: float | None = None
    risk_score: float | None = None
    stress_detected: bool = False
    weather: dict[str, float] | None = None


def build_point_context(
    point: CapturePoint,
    sowing_date: date | None = None,
    crop_stages: list[dict[str, Any]] | None = None,
) -> PointContext:
    """组装匹配上下文。生育期优先取分析结果；缺分析时用日历法兜底——
    生育期由播种日期确定性可算，不应依赖"恰好有张能分析的照片"。"""
    analysis: Analysis | None = point.analysis
    weather: WeatherSample | None = point.weather

    stage_name = (analysis.growth_stage or {}).get("name") if analysis else None
    if stage_name is None and sowing_date is not None:
        fallback = calendar_growth_stage(
            CaptureContext(
                captured_at=point.captured_at,
                lng=point.lng,
                lat=point.lat,
                sowing_date=sowing_date,
                crop_stages=list(crop_stages or []),
            )
        )
        if fallback:
            stage_name = fallback.get("name")

    return PointContext(
        seq=point.seq,
        stage_name=stage_name,
        vigor_level=analysis.vigor_level if analysis else None,
        ndvi=analysis.ndvi if analysis else None,
        risk_score=analysis.risk_score if analysis else None,
        stress_detected=bool(analysis and analysis.disease_detections),
        weather=(
            {f: getattr(weather, f) for f in _WEATHER_FIELDS}
            if weather else None
        ),
    )


# ---------- 条件匹配 ----------


def _match_operator(value: Any, spec: Any) -> bool:
    """标量即 eq；字典支持 lt/lte/gt/gte/eq/between。value 为 None 一律不命中。"""
    if value is None:
        return False
    if not isinstance(spec, dict):
        return value == spec
    for op, operand in spec.items():
        if op == "lt" and not value < operand:
            return False
        elif op == "lte" and not value <= operand:
            return False
        elif op == "gt" and not value > operand:
            return False
        elif op == "gte" and not value >= operand:
            return False
        elif op == "eq" and value != operand:
            return False
        elif op == "between" and not (operand[0] <= value <= operand[1]):
            return False
        elif op not in {"lt", "lte", "gt", "gte", "eq", "between"}:
            raise ValueError(f"未知算子：{op}")
    return True


def evaluate(condition: dict[str, Any], ctx: PointContext) -> tuple[bool, dict[str, Any]]:
    """评估条件是否命中，同时收集命中字段的观测值供动作模板插值。

    返回 (是否命中, 绑定值)；不命中时绑定值无意义返回空。
    """
    bindings: dict[str, Any] = {}
    try:
        for key, spec in condition.items():
            if key == "stage":
                # 无生育期数据（如未关联种植批次）时 stage 条件不命中
                if ctx.stage_name is None or ctx.stage_name != str(spec):
                    return False, {}
                bindings["stage"] = ctx.stage_name
            elif key in {"vigor_level", "ndvi", "risk_score"}:
                value = getattr(ctx, key)
                if not _match_operator(value, spec):
                    return False, {}
                if value is not None:
                    bindings[key] = value
            elif key == "stress_detected":
                if bool(spec) != ctx.stress_detected:
                    return False, {}
            elif key == "weather":
                if ctx.weather is None:
                    return False, {}
                for field_name, field_spec in spec.items():
                    if field_name not in _WEATHER_FIELDS:
                        raise ValueError(f"未知天气字段：{field_name}")
                    value = ctx.weather.get(field_name)
                    if not _match_operator(value, field_spec):
                        return False, {}
                    if value is not None:
                        bindings[field_name] = value
            else:
                raise ValueError(f"未知条件键：{key}")
        return True, bindings
    except ValueError:
        raise
    except Exception:  # 数据形态异常一律不命中，不让单条坏规则拖垮生成
        return False, {}


# ---------- 模板插值（缺参保留占位符，不抛错）----------


class _KeepMissing(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_action(
    template: str,
    params: dict[str, Any] | None,
    ctx: PointContext,
    bindings: dict[str, Any],
) -> str:
    """变量优先级：显式 params > 命中观测值 bindings > 上下文默认。

    缺参保留占位符便于排查；stage 缺失时置空串避免渲染出 "None"；
    位置占位符 `{}` 会令 Formatter 抛 IndexError——返回原模板而非让生成 500。
    """
    variables = _KeepMissing(**{**bindings, **(params or {})})
    variables.setdefault("stage", ctx.stage_name or "")
    variables["seq"] = ctx.seq
    try:
        return string.Formatter().vformat(template, (), variables)
    except (IndexError, ValueError):
        return template


# ---------- 快照与生成 ----------


def freeze_snapshot(rule: Rule) -> dict[str, Any]:
    return {
        "rule_key": rule.rule_key,
        "tier": rule.tier,
        "priority": rule.priority,
        "condition": rule.condition,
        "action": rule.action,
        "params": rule.params,
        "source": rule.source,
        "version": rule.version,
    }


def compute_advice_pairs(
    db: Session,
    patrol_id: int,
    extra_rules: list[Rule] | None = None,
    exclude_keys: set[str] | None = None,
) -> set[tuple[int, str]]:
    """纯计算：给定当前规则集，返回该巡检会产生的 (capture_point_id, rule_key) 集合。

    只读零写入——影子运行（shadow_run.py）依赖此性质做新旧规则对比，
    与 generate_advices_for_patrol 共享同一套加载与匹配逻辑。
    extra_rules：内存中的临时规则（draft 视图）；exclude_keys：从现库规则中剔除的 key。
    """
    patrol = db.scalars(
        select(Patrol)
        .options(
            selectinload(Patrol.planting).selectinload(Planting.crop),
            selectinload(Patrol.capture_points)
            .selectinload(CapturePoint.analysis),
            selectinload(Patrol.capture_points).selectinload(CapturePoint.weather),
        )
        .where(Patrol.id == patrol_id)
    ).first()
    if patrol is None:
        raise LookupError(f"巡检任务不存在：patrol_id={patrol_id}")

    crop_id = patrol.planting.crop_id if patrol.planting else None
    rules = [
        r for r in db.scalars(select(Rule).where(Rule.active.is_(True))).all()
        if r.crop_id is None or (crop_id is not None and r.crop_id == crop_id)
    ]
    if exclude_keys:
        rules = [r for r in rules if r.rule_key not in exclude_keys]
    if extra_rules:
        rules = rules + [
            r for r in extra_rules
            if r.crop_id is None or (crop_id is not None and r.crop_id == crop_id)
        ]

    planting = patrol.planting
    pairs: set[tuple[int, str]] = set()
    for point in patrol.capture_points:
        ctx = build_point_context(
            point,
            sowing_date=planting.sowing_date if planting else None,
            crop_stages=list(planting.crop.stages) if planting and planting.crop else None,
        )
        for rule in rules:
            ok, _bindings = evaluate(rule.condition or {}, ctx)
            if ok:
                pairs.add((point.id, rule.rule_key))
    return pairs


def generate_advices_for_patrol(db: Session, patrol_id: int) -> dict[str, int]:
    patrol = db.scalars(
        select(Patrol)
        .options(
            selectinload(Patrol.planting),
            selectinload(Patrol.capture_points)
            .selectinload(CapturePoint.analysis),
            selectinload(Patrol.capture_points).selectinload(CapturePoint.weather),
        )
        .where(Patrol.id == patrol_id)
    ).first()
    if patrol is None:
        raise LookupError(f"巡检任务不存在：patrol_id={patrol_id}")

    crop_id = patrol.planting.crop_id if patrol.planting else None
    rules = [
        r for r in db.scalars(select(Rule).where(Rule.active.is_(True))).all()
        # 作物无关规则恒可命中；作物专属规则仅在种植批次匹配时参与
        if r.crop_id is None or (crop_id is not None and r.crop_id == crop_id)
    ]
    rules.sort(key=lambda r: (-_PRIORITY_WEIGHT.get(r.priority, 2), r.rule_key))

    # 人工决策是事实：先记录，再清 suggested，重生成时永不覆盖 accepted/rejected
    decisions: dict[tuple[int | None, str], str] = {}
    existing = db.scalars(select(Advice).where(Advice.patrol_id == patrol_id)).all()
    for adv in existing:
        decisions[(adv.capture_point_id, adv.rule_key)] = adv.status
    deleted_suggested = db.execute(
        delete(Advice).where(Advice.patrol_id == patrol_id, Advice.status == "suggested")
    ).rowcount
    db.flush()

    created = skipped_decided = 0
    planting = patrol.planting
    for point in patrol.capture_points:
        ctx = build_point_context(
            point,
            sowing_date=planting.sowing_date if planting else None,
            crop_stages=list(planting.crop.stages) if planting and planting.crop else None,
        )
        hits = [(rule,) + evaluate(rule.condition or {}, ctx) for rule in rules]
        top = [(rule, bindings) for rule, ok, bindings in hits if ok][:TOP_K_PER_POINT]
        for rule, bindings in top:
            if decisions.get((point.id, rule.rule_key)) in {"accepted", "rejected"}:
                skipped_decided += 1
                continue
            db.add(
                Advice(
                    patrol_id=patrol.id,
                    capture_point_id=point.id,
                    rule_id=rule.id,
                    rule_key=rule.rule_key,
                    rule_snapshot=freeze_snapshot(rule),
                    content=render_action(rule.action, rule.params, ctx, bindings),
                    priority=rule.priority,
                    status="suggested",
                )
            )
            created += 1

    db.commit()
    return {
        "created": created,
        "deleted_suggested": deleted_suggested or 0,
        "skipped_decided": skipped_decided,
        "points": len(patrol.capture_points),
        "rules_active": len(rules),
    }
