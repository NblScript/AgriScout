"""风险驱动巡检计划 planner-v1（计划 0015 的 planner-v0 + D22，纯函数，不读写数据库）。

输入全部在用的株（每株状态 + 距上次看到 / 上次合格叶背的天数 + 邻株最高模型分）和环境摘要，输出四张名单：

- **确认**（推给人看）：模型判为早期、或模型分达到确认阈值的株，按分数排序，受人工预算限制。
  人工判为健康的株，之后又拍到的合格叶背图分数达到早期阈值，也重新推给人（D22，v1 起）。
- **补拍**（叶背多角度重拍）：按模型分、邻株、环境、叶背陈旧程度打分，预算随环境指数在基础比例和高风险比例之间插值。
- **全覆盖**：太久没看到的株全部进入。
- **抽查**：从剩下的株里按固定比例随机抽，种子由 (地块, 计划日) 决定，结果可复现。

每株最多出现在一张名单里（确认 > 补拍 > 全覆盖 > 抽查）。风险**不用来减少巡检**：环境风险低时全覆盖和抽查照样生成。
公式和默认参数都是启发式，不是训练出来的模型；每条结果都把各项分量写进 rationale，便于审计和答辩如实说明。
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date
from typing import Any

from app.core.timeutil import to_utc
from app.services.plant_state import PlantState

PLAN_VERSION = "planner-v1"
LISTS = ("confirm", "reshoot", "coverage", "random")
# 名单 → RevisitTask.task_type
TASK_TYPES = {"confirm": "label", "reshoot": "revisit", "coverage": "coverage", "random": "random"}

# 补拍的叶背多角度序列（与 rover/views.example.json 同结构，rover 可直接解析）；角度与高度是示例值，待试拍校准
DEFAULT_RESHOOT_VIEWS: tuple[dict[str, Any], ...] = (
    {"name": "under-35", "side": "under", "pitch_deg": 35, "yaw_deg": 0, "height_m": 0.2, "fill_light": True},
    {"name": "under-50", "side": "under", "pitch_deg": 50, "yaw_deg": 0, "height_m": 0.2, "fill_light": True},
    {"name": "under-65", "side": "under", "pitch_deg": 65, "yaw_deg": 0, "height_m": 0.2, "fill_light": True},
)


@dataclass(frozen=True)
class PlannerParams:
    """全部是经验初值，待田间试用后调整。"""

    # 确认：模型分达到这个阈值就推给人（与每株状态的「明显」占位阈值一致）；人工每天最多确认的株数
    confirm_threshold: float = 0.7
    human_budget: int = 5
    # 人工判为健康后又拍到合格叶背图、分数达到这个值就重新推给人（与每株状态的「早期」占位阈值一致，D22）
    healthy_recheck_threshold: float = 0.4
    # 补拍打分权重：模型分、邻株最高分、环境指数、叶背陈旧程度；上次叶背不合格再加分
    w_model: float = 0.4
    w_neighbor: float = 0.2
    w_env: float = 0.2
    w_stale: float = 0.2
    bad_quality_bonus: float = 0.1
    # 环境指数缺失（覆盖率不足）时按中值算，不当成低风险
    env_missing_value: float = 0.5
    # 补拍预算占在用株数的比例：环境指数 0 时取基础比例，1 时取高风险比例，中间线性插值
    reshoot_base_ratio: float = 0.10
    reshoot_high_ratio: float = 0.25
    # 全覆盖周期：这么多天没被看到的株必须进入全覆盖；叶背陈旧程度也按它归一
    coverage_period_days: float = 7.0
    # 抽查比例（至少 1 株）
    random_ratio: float = 0.05
    random_min: int = 1
    # 任务优先级（设备领任务时按它排序）：确认、补拍用各自分数，全覆盖与抽查用固定值
    coverage_priority: float = 0.3
    random_priority: float = 0.1
    reshoot_views: tuple[dict[str, Any], ...] = field(default=DEFAULT_RESHOOT_VIEWS)

    def with_overrides(self, overrides: dict[str, Any] | None) -> "PlannerParams":
        """按请求覆盖参数；只允许已知的数值参数，类型和范围不对直接报错。"""
        if not overrides:
            return self
        numeric = {f.name: f.type for f in fields(self) if f.name != "reshoot_views"}
        clean: dict[str, Any] = {}
        for key, value in overrides.items():
            if key not in numeric:
                raise ValueError(f"未知的计划参数：{key}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"计划参数 {key} 必须是数字")
            if value < 0:
                raise ValueError(f"计划参数 {key} 不能为负")
            if numeric[key] in (int, "int"):
                if int(value) != value:
                    raise ValueError(f"计划参数 {key} 必须是整数")
                clean[key] = int(value)
            else:
                clean[key] = float(value)
        result = replace(self, **clean)
        if not 0 <= result.reshoot_base_ratio <= result.reshoot_high_ratio <= 1:
            raise ValueError("补拍比例需满足 0 ≤ 基础比例 ≤ 高风险比例 ≤ 1")
        if result.random_ratio > 1 or result.coverage_period_days <= 0:
            raise ValueError("抽查比例不能超过 1，全覆盖周期必须为正")
        return result


DEFAULT_PARAMS = PlannerParams()


@dataclass(frozen=True)
class UnitInput:
    unit_id: int
    key: str
    state: PlantState
    days_since_seen: float | None  # None = 从没被拍到
    days_since_under_ok: float | None  # None = 从没有合格叶背图
    neighbor_max_score: float = 0.0
    row_no: int | None = None
    position_no: int | None = None


@dataclass(frozen=True)
class PlanItem:
    unit_id: int
    key: str
    list_name: str
    score: float
    priority: float
    rationale: dict[str, Any]

    @property
    def task_type(self) -> str:
        return TASK_TYPES[self.list_name]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def plan_seed(field_id: int, plan_date: date) -> str:
    """抽查种子：同一地块同一天重复生成，抽到的株不变。"""
    return f"{PLAN_VERSION}:{field_id}:{plan_date.isoformat()}"


def env_value(env_index: float | None, params: PlannerParams) -> tuple[float, bool]:
    """(用于打分和预算的环境值, 是否缺失)。"""
    if env_index is None:
        return params.env_missing_value, True
    return _clamp(env_index), False


def reshoot_budget(n_units: int, env_index: float | None, params: PlannerParams = DEFAULT_PARAMS) -> int:
    value, _ = env_value(env_index, params)
    ratio = params.reshoot_base_ratio + (params.reshoot_high_ratio - params.reshoot_base_ratio) * value
    return min(n_units, max(1, round(ratio * n_units))) if n_units else 0


def _human_symptomatic(unit: UnitInput) -> bool:
    return unit.state.source == "human" and unit.state.state == "symptomatic"


def _scored_after_review(st: PlantState) -> bool:
    """模型分所依据的叶背图是在人工结论之后拍的（人还没看过这张图）。"""
    return (st.reviewed_at is not None and st.model_scored_at is not None
            and to_utc(st.model_scored_at) > to_utc(st.reviewed_at))


def _confirm_entry(unit: UnitInput, params: PlannerParams) -> dict[str, Any] | None:
    st = unit.state
    if _human_symptomatic(unit):
        return None  # 已经人工确认为明显，不再推
    # 人工结论晚于最新照片：这些照片已经被人看过，模型分不再触发确认
    reviewed = (st.source == "human" and st.reviewed_at is not None and st.last_seen_at is not None
                and st.reviewed_at >= st.last_seen_at)
    triggers = []
    if st.state == "early" and st.source != "human":
        triggers.append("model_early")
    # 人工判为健康不等于以后都健康：之后的新叶背图分数达到早期阈值，重新推给人（D22）
    if (st.source == "human" and st.state == "healthy" and st.model_score is not None
            and st.model_score >= params.healthy_recheck_threshold and _scored_after_review(st)):
        triggers.append("model_early_after_human_healthy")
    if st.model_score is not None and st.model_score >= params.confirm_threshold and not reviewed:
        triggers.append("model_score_over_confirm_threshold")
    if not triggers:
        return None
    entry = {"triggers": triggers, "state": st.state, "source": st.source, "model_score": st.model_score,
             "confirm_threshold": params.confirm_threshold}
    if "model_early_after_human_healthy" in triggers:
        entry["healthy_recheck_threshold"] = params.healthy_recheck_threshold
    return entry


def _reshoot_components(unit: UnitInput, env: float, env_missing: bool, params: PlannerParams) -> dict[str, Any]:
    st = unit.state
    model = st.model_score or 0.0
    stale = 1.0 if unit.days_since_under_ok is None else _clamp(unit.days_since_under_ok / params.coverage_period_days)
    bad_quality = st.last_under_accepted is False
    parts = {
        "model": round(params.w_model * model, 6),
        "neighbor": round(params.w_neighbor * _clamp(unit.neighbor_max_score), 6),
        "env": round(params.w_env * env, 6),
        "stale": round(params.w_stale * stale, 6),
        "bad_quality": params.bad_quality_bonus if bad_quality else 0.0,
    }
    return {
        "score": round(sum(parts.values()), 6), "parts": parts,
        "inputs": {"model_score": st.model_score, "neighbor_max_score": unit.neighbor_max_score,
                   "env_index": None if env_missing else env, "env_used": env, "env_missing": env_missing,
                   "days_since_under_ok": unit.days_since_under_ok, "stale": round(stale, 6),
                   "last_under_accepted": st.last_under_accepted},
        "weights": {"model": params.w_model, "neighbor": params.w_neighbor, "env": params.w_env,
                    "stale": params.w_stale, "bad_quality_bonus": params.bad_quality_bonus},
    }


def build_plan(
    units: Sequence[UnitInput],
    env: dict[str, Any],
    *,
    plan_date: date,
    seed: str,
    params: PlannerParams = DEFAULT_PARAMS,
) -> dict[str, Any]:
    """生成一天的巡检计划。env 是 ``greenhouse_env.summarize`` 的 ``index`` 与 ``morning_window``。"""
    env_index = (env.get("index") or {}).get("env_index")
    window = env.get("morning_window")
    env_used, env_missing = env_value(env_index, params)
    ordered = sorted(units, key=lambda u: u.key)
    taken: set[int] = set()
    lists: dict[str, list[PlanItem]] = {name: [] for name in LISTS}

    # 1. 确认：按模型分排序，人工预算截断；没进预算的株照样参与后面的名单
    confirm_pool = []
    for unit in ordered:
        entry = _confirm_entry(unit, params)
        if entry is not None:
            confirm_pool.append((unit, entry))
    confirm_pool.sort(key=lambda pair: (-(pair[0].state.model_score or 0.0), pair[0].key))
    for rank, (unit, entry) in enumerate(confirm_pool[:params.human_budget], start=1):
        score = unit.state.model_score or 0.0
        lists["confirm"].append(PlanItem(unit.unit_id, unit.key, "confirm", score, _clamp(score), {
            **entry, "rank": rank, "candidates": len(confirm_pool), "human_budget": params.human_budget,
        }))
        taken.add(unit.unit_id)

    # 2. 补拍：剩余株全部打分，取预算内的高分株。人工已确认为明显的株不占补拍预算（补拍是为了把没看清的看清），
    #    它们仍会进全覆盖或抽查，保证持续有照片
    budget = reshoot_budget(len(ordered), env_index, params)
    scored = []
    for unit in ordered:
        if unit.unit_id in taken or _human_symptomatic(unit):
            continue
        scored.append((unit, _reshoot_components(unit, env_used, env_missing, params)))
    scored.sort(key=lambda pair: (-pair[1]["score"], pair[0].key))
    for rank, (unit, comp) in enumerate(scored[:budget], start=1):
        triggers = ["top_reshoot_score"]
        if comp["parts"]["bad_quality"]:
            triggers.append("last_under_rejected")
        if window is not None:
            triggers.append("morning_window")
        lists["reshoot"].append(PlanItem(unit.unit_id, unit.key, "reshoot", comp["score"], _clamp(comp["score"]), {
            **comp, "triggers": triggers, "rank": rank, "budget": budget,
        }))
        taken.add(unit.unit_id)

    # 3. 全覆盖：到期的全部进入，不受预算限制
    for unit in ordered:
        if unit.unit_id in taken:
            continue
        due = unit.days_since_seen is None or unit.days_since_seen >= params.coverage_period_days
        if due:
            lists["coverage"].append(PlanItem(unit.unit_id, unit.key, "coverage", params.coverage_priority,
                                              params.coverage_priority, {
                "triggers": ["never_seen" if unit.days_since_seen is None else "coverage_due"],
                "days_since_seen": unit.days_since_seen, "coverage_period_days": params.coverage_period_days,
            }))
            taken.add(unit.unit_id)

    # 4. 抽查：剩余株按固定比例随机抽，种子固定
    remaining = [u for u in ordered if u.unit_id not in taken]
    n_random = min(len(remaining), max(params.random_min, round(params.random_ratio * len(ordered)))) if remaining else 0
    rng = random.Random(seed)
    for unit in sorted(rng.sample(remaining, n_random), key=lambda u: u.key):
        lists["random"].append(PlanItem(unit.unit_id, unit.key, "random", params.random_priority,
                                        params.random_priority, {
            "triggers": ["random_spot_check"], "random_ratio": params.random_ratio, "pool": len(remaining),
            "seed": seed, "state": unit.state.state, "model_score": unit.state.model_score,
        }))

    return {
        "plan_version": PLAN_VERSION,
        "plan_date": plan_date,
        "seed": seed,
        "units": len(ordered),
        "env": {**(env.get("index") or {}), "env_used": env_used, "env_missing": env_missing},
        "window": window,
        "reshoot_budget": budget,
        "lists": lists,
        "params": {**asdict(params), "reshoot_views": [dict(v) for v in params.reshoot_views]},
    }
