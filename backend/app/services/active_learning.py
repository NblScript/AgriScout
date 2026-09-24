"""主动复巡与主动学习候选排序。

本模块只做纯计算，不读写数据库，也不依赖 API 或模型。候选点把图像质量、
模型不确定性、风险、时序变化、代表性和执行成本压缩为三个可解释任务之一：

``revisit``
    证据质量不足或风险变化值得再次采集，优先请求复拍/复巡。
``label``
    图像质量足够但模型不确定，优先交给专家标注。
``random``
    作为代表性或低风险抽查，防止只看模型认为重要的点。

输入信号约定为 0--1（``cost`` 为非负成本单位）；超出 0--1 的信号会在
计算时截断，避免单个脏数据拖垮候选队列。选择约束由 :class:`SelectionConstraints`
提供，预算使用与候选 ``cost`` 相同的单位。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Iterable, Literal


TaskType = Literal["revisit", "label", "random"]
TASK_TYPES: frozenset[str] = frozenset({"revisit", "label", "random"})
_TASK_TIE_ORDER: dict[str, int] = {"revisit": 0, "label": 1, "random": 2}


@dataclass(frozen=True, slots=True)
class ActiveLearningCandidate:
    """待排序的一个采样点或图像。

    除 ``candidate_id`` 和 ``cost`` 外的数值信号都按 0--1 解释，数值越大
    表示越强。``quality`` 越大表示图像越清晰；因此复巡的质量缺口是
    ``1 - quality``。能力开关用于在没有云台、没有可用标注或不允许随机抽查
    时禁用相应任务类型。
    """

    candidate_id: str
    quality: float
    uncertainty: float
    risk: float
    change: float
    representativeness: float
    cost: float
    already_labeled: bool = False
    revisitable: bool = True
    labelable: bool = True
    randomizable: bool = True

    def __post_init__(self) -> None:
        if not self.candidate_id or not isinstance(self.candidate_id, str):
            raise ValueError("candidate_id 必须是非空字符串")
        try:
            cost = float(self.cost)
        except (TypeError, ValueError) as exc:
            raise ValueError("cost 必须是有限的非负数") from exc
        if not isfinite(cost) or cost < 0:
            raise ValueError("cost 必须是有限的非负数")
        object.__setattr__(self, "cost", cost)


# ``Candidate`` 是较短的公开别名，方便调用方按业务语义传入候选。
Candidate = ActiveLearningCandidate


@dataclass(frozen=True, slots=True)
class SelectionConstraints:
    """候选选择约束和任务分类阈值。

    ``rank_candidates`` 使用阈值决定任务类型，但不会截断数量或预算；
    ``select_tasks`` 在排序结果上再应用预算和数量约束。
    """

    budget: float | None = None
    max_tasks: int | None = None
    max_revisit: int | None = None
    max_label: int | None = None
    max_random: int | None = None
    min_score: float = 0.0
    revisit_quality_threshold: float = 0.45
    label_uncertainty_threshold: float = 0.55
    label_quality_floor: float = 0.50
    random_representativeness_threshold: float = 0.60
    allowed_task_types: frozenset[str] = field(
        default_factory=lambda: frozenset(TASK_TYPES),
    )

    def __post_init__(self) -> None:
        for name in ("budget", "min_score"):
            value = getattr(self, name)
            if value is not None:
                try:
                    numeric = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{name} 必须是有限非负数") from exc
                if not isfinite(numeric) or (name == "budget" and numeric < 0):
                    raise ValueError(f"{name} 必须是有限非负数")
                object.__setattr__(self, name, numeric)

        if self.min_score < 0 or self.min_score > 1:
            raise ValueError("min_score 必须在 0--1 之间")
        for name in ("revisit_quality_threshold", "label_uncertainty_threshold",
                     "label_quality_floor", "random_representativeness_threshold"):
            value = getattr(self, name)
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} 必须在 0--1 之间") from exc
            if not isfinite(numeric) or not 0 <= numeric <= 1:
                raise ValueError(f"{name} 必须在 0--1 之间")
            object.__setattr__(self, name, numeric)

        for name in ("max_tasks", "max_revisit", "max_label", "max_random"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} 必须是非负整数或 None")

        allowed = frozenset(self.allowed_task_types)
        unknown = allowed - TASK_TYPES
        if unknown:
            raise ValueError(f"allowed_task_types 含未知任务类型：{sorted(unknown)}")
        object.__setattr__(self, "allowed_task_types", allowed)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """排序后的可解释任务建议。"""

    candidate_id: str
    task_type: TaskType
    score: float
    rank: int
    task_scores: dict[str, float]
    signals: dict[str, float]
    reasons: tuple[str, ...]
    cost: float


# 便于调用方使用更短的名字。
RankedTask = RankedCandidate


def _signal(value: float, name: str) -> float:
    """将信号安全地转换为 0--1；非数值/NaN 仍显式报错。"""

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限数字") from exc
    if not isfinite(numeric):
        raise ValueError(f"{name} 必须是有限数字")
    return max(0.0, min(1.0, numeric))


def _candidate_signals(candidate: ActiveLearningCandidate) -> dict[str, float]:
    quality = _signal(candidate.quality, "quality")
    return {
        "quality": quality,
        "quality_gap": 1.0 - quality,
        "uncertainty": _signal(candidate.uncertainty, "uncertainty"),
        "risk": _signal(candidate.risk, "risk"),
        "change": _signal(candidate.change, "change"),
        "representativeness": _signal(
            candidate.representativeness, "representativeness",
        ),
        # 成本可用任意非负单位输入；评分只把超过 1 的部分视为满额惩罚。
        "cost": min(1.0, float(candidate.cost)),
    }


def _available_tasks(
    candidate: ActiveLearningCandidate,
    constraints: SelectionConstraints,
) -> tuple[TaskType, ...]:
    available: list[TaskType] = []
    if candidate.revisitable and "revisit" in constraints.allowed_task_types:
        available.append("revisit")
    if (
        candidate.labelable
        and not candidate.already_labeled
        and "label" in constraints.allowed_task_types
    ):
        available.append("label")
    if candidate.randomizable and "random" in constraints.allowed_task_types:
        available.append("random")
    return tuple(available)


def score_candidate(
    candidate: ActiveLearningCandidate,
    task_type: TaskType,
) -> float:
    """计算候选执行某一任务的价值，返回 0--1 分数。

    权重刻意保持显式，便于答辩或实验报告解释。复巡偏重质量缺口，标注偏重
    不确定性，随机抽查偏重代表性；三类任务都扣除执行成本。
    """

    if task_type not in TASK_TYPES:
        raise ValueError(f"未知任务类型：{task_type}")
    s = _candidate_signals(candidate)
    if task_type == "revisit":
        raw = (
            0.36 * s["quality_gap"]
            + 0.26 * s["risk"]
            + 0.20 * s["change"]
            + 0.10 * s["uncertainty"]
            + 0.08 * s["representativeness"]
            - 0.14 * s["cost"]
        )
    elif task_type == "label":
        raw = (
            0.30 * s["uncertainty"]
            + 0.24 * s["risk"]
            + 0.18 * s["change"]
            + 0.18 * s["representativeness"]
            + 0.10 * s["quality"]
            - 0.16 * s["cost"]
        )
    else:  # random
        raw = (
            0.50 * s["representativeness"]
            + 0.20 * s["quality"]
            + 0.15 * (1.0 - s["uncertainty"])
            + 0.15 * (1.0 - s["risk"])
            - 0.12 * s["cost"]
        )
    return max(0.0, min(1.0, round(raw, 6)))


def classify_task(
    candidate: ActiveLearningCandidate,
    constraints: SelectionConstraints | None = None,
) -> TaskType | None:
    """按信号和能力约束选择任务类型。

    低质量证据优先复巡；质量足够且不确定性高优先标注；代表性高的正常/低风险
    候选优先随机抽查。没有达到阈值时，退回可用任务中得分最高者。
    """

    config = constraints or SelectionConstraints()
    available = _available_tasks(candidate, config)
    if not available:
        return None
    signals = _candidate_signals(candidate)
    if (
        "revisit" in available
        and signals["quality"] <= config.revisit_quality_threshold
    ):
        return "revisit"
    if (
        "label" in available
        and signals["quality"] >= config.label_quality_floor
        and signals["uncertainty"] >= config.label_uncertainty_threshold
    ):
        return "label"
    if (
        "random" in available
        and signals["representativeness"]
        >= config.random_representativeness_threshold
    ):
        return "random"

    return max(
        available,
        key=lambda task: (score_candidate(candidate, task), -_TASK_TIE_ORDER[task]),
    )


def _reasons(
    candidate: ActiveLearningCandidate,
    task_type: TaskType,
    signals: dict[str, float],
    constraints: SelectionConstraints,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if task_type == "revisit":
        if signals["quality"] <= constraints.revisit_quality_threshold:
            reasons.append("quality_below_revisit_threshold")
        if signals["risk"] >= 0.5:
            reasons.append("risk_high")
        if signals["change"] >= 0.5:
            reasons.append("change_high")
        if not reasons:
            reasons.append("highest_available_revisit_score")
    elif task_type == "label":
        if signals["uncertainty"] >= constraints.label_uncertainty_threshold:
            reasons.append("uncertainty_high")
        if signals["quality"] >= constraints.label_quality_floor:
            reasons.append("quality_suitable_for_label")
        if signals["risk"] >= 0.5:
            reasons.append("risk_high")
        if not reasons:
            reasons.append("highest_available_label_score")
    else:
        if (
            signals["representativeness"]
            >= constraints.random_representativeness_threshold
        ):
            reasons.append("representativeness_high")
        if signals["risk"] < 0.5:
            reasons.append("low_risk_coverage")
        if not reasons:
            reasons.append("highest_available_random_score")
    if candidate.cost > 0:
        reasons.append("cost_penalty_applied")
    return tuple(reasons)


def rank_candidates(
    candidates: Iterable[ActiveLearningCandidate],
    constraints: SelectionConstraints | None = None,
) -> list[RankedCandidate]:
    """返回全部可执行候选的稳定排序。

    排序键为 ``score`` 降序、``candidate_id`` 升序，因此相同输入始终得到
    相同结果。数量、预算和最低分只在 :func:`select_tasks` 中应用。
    """

    config = constraints or SelectionConstraints()
    ranked: list[RankedCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in seen:
            raise ValueError(f"candidate_id 重复：{candidate.candidate_id}")
        seen.add(candidate.candidate_id)
        task_type = classify_task(candidate, config)
        if task_type is None:
            continue
        signals = _candidate_signals(candidate)
        task_scores = {
            task: score_candidate(candidate, task)
            for task in _available_tasks(candidate, config)
        }
        ranked.append(
            RankedCandidate(
                candidate_id=candidate.candidate_id,
                task_type=task_type,
                score=task_scores[task_type],
                rank=0,
                task_scores=task_scores,
                signals=signals,
                reasons=_reasons(candidate, task_type, signals, config),
                cost=float(candidate.cost),
            )
        )

    ranked.sort(key=lambda row: (-row.score, row.candidate_id))
    return [replace(row, rank=index) for index, row in enumerate(ranked, start=1)]


def select_tasks(
    candidates: Iterable[ActiveLearningCandidate],
    constraints: SelectionConstraints | None = None,
) -> list[RankedCandidate]:
    """在排序结果上应用预算、最低分和各任务数量约束。

    采用稳定的贪心选择：按解释分数从高到低扫描，超出预算或配额的候选跳过，
    后续更便宜的候选仍有机会入选。返回的 ``rank`` 保留全体候选中的全局排名。
    """

    config = constraints or SelectionConstraints()
    ranked = rank_candidates(candidates, config)
    counts: dict[str, int] = {task: 0 for task in TASK_TYPES}
    selected: list[RankedCandidate] = []
    spent = 0.0
    max_by_task = {
        "revisit": config.max_revisit,
        "label": config.max_label,
        "random": config.max_random,
    }
    for row in ranked:
        if row.score < config.min_score:
            continue
        if config.max_tasks is not None and len(selected) >= config.max_tasks:
            break
        quota = max_by_task[row.task_type]
        if quota is not None and counts[row.task_type] >= quota:
            continue
        if config.budget is not None and spent + row.cost > config.budget + 1e-9:
            continue
        selected.append(row)
        counts[row.task_type] += 1
        spent += row.cost
    return selected


def rank_active_learning_candidates(
    candidates: Iterable[ActiveLearningCandidate],
    constraints: SelectionConstraints | None = None,
) -> list[RankedCandidate]:
    """显式命名别名，供业务层调用。"""

    return rank_candidates(candidates, constraints)


def select_active_learning_tasks(
    candidates: Iterable[ActiveLearningCandidate],
    constraints: SelectionConstraints | None = None,
) -> list[RankedCandidate]:
    """显式命名别名，供业务层调用。"""

    return select_tasks(candidates, constraints)


__all__ = [
    "TASK_TYPES",
    "TaskType",
    "ActiveLearningCandidate",
    "Candidate",
    "SelectionConstraints",
    "RankedCandidate",
    "RankedTask",
    "score_candidate",
    "classify_task",
    "rank_candidates",
    "select_tasks",
    "rank_active_learning_candidates",
    "select_active_learning_tasks",
]
