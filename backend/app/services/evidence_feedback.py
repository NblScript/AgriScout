"""预警证据反馈与随访状态机（纯函数服务）。

这里不直接依赖 ORM，也不写数据库。风险预测、复巡任务和人工复核路由
可以把本模块作为同一套状态和完整性规则使用，避免在多个入口各自定义
``confirmed_positive`` 等状态。

一个完整的反馈记录至少要能回答：

* 哪条预警/预测（``alert_id``）对应哪个观察区域；
* 预测窗口和产生结论时使用的模型版本是什么；
* 原始证据引用在哪里；
* 当前随访结论处于哪个状态。

``intervened`` 表示随访期间发生了处置，后续结果不能直接当成未干预的
阳性或阴性标签。它和两个 confirmed 状态一样是终态；如果需要重新观察，
应由业务层新建一条随访记录，而不是覆盖历史结论。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeAlias


__all__ = [
    "FeedbackStatus",
    "CONFIRMED_POSITIVE",
    "CONFIRMED_NEGATIVE",
    "PENDING",
    "INSUFFICIENT",
    "INTERVENED",
    "UNKNOWN",
    "VALID_STATUSES",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "InvalidStatusError",
    "InvalidTransitionError",
    "CompletenessReport",
    "validate_status",
    "validate_transition",
    "is_valid_transition",
    "transition_status",
    "apply_transition",
    "check_completeness",
    "assert_complete",
    "is_complete",
]


FeedbackStatus: TypeAlias = Literal[
    "confirmed_positive",
    "confirmed_negative",
    "pending",
    "insufficient",
    "intervened",
    "unknown",
]

CONFIRMED_POSITIVE: Final = "confirmed_positive"
CONFIRMED_NEGATIVE: Final = "confirmed_negative"
PENDING: Final = "pending"
INSUFFICIENT: Final = "insufficient"
INTERVENED: Final = "intervened"
UNKNOWN: Final = "unknown"

VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {
        CONFIRMED_POSITIVE,
        CONFIRMED_NEGATIVE,
        PENDING,
        INSUFFICIENT,
        INTERVENED,
        UNKNOWN,
    }
)

# ``None`` represents a new feedback record.  A record is created as pending;
# all other transitions require an existing status.  ``insufficient`` and
# ``unknown`` may be revisited after more evidence is collected.  Confirmed
# outcomes and intervened are immutable terminal outcomes; a new observation
# should create a new feedback record instead of rewriting history.
ALLOWED_TRANSITIONS: Final[dict[str | None, frozenset[str]]] = {
    None: frozenset({PENDING}),
    PENDING: frozenset(
        {
            PENDING,
            CONFIRMED_POSITIVE,
            CONFIRMED_NEGATIVE,
            INSUFFICIENT,
            INTERVENED,
            UNKNOWN,
        }
    ),
    INSUFFICIENT: frozenset(
        {
            INSUFFICIENT,
            PENDING,
            CONFIRMED_POSITIVE,
            CONFIRMED_NEGATIVE,
            INTERVENED,
            UNKNOWN,
        }
    ),
    UNKNOWN: frozenset(
        {
            UNKNOWN,
            PENDING,
            CONFIRMED_POSITIVE,
            CONFIRMED_NEGATIVE,
            INSUFFICIENT,
            INTERVENED,
        }
    ),
    CONFIRMED_POSITIVE: frozenset({CONFIRMED_POSITIVE}),
    CONFIRMED_NEGATIVE: frozenset({CONFIRMED_NEGATIVE}),
    INTERVENED: frozenset({INTERVENED}),
}

TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {CONFIRMED_POSITIVE, CONFIRMED_NEGATIVE, INTERVENED}
)


class InvalidStatusError(ValueError):
    """反馈状态不在协议允许的六个值中。"""


class InvalidTransitionError(ValueError):
    """状态机不允许从当前状态转移到目标状态。"""


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    """反馈记录完整性检查结果。

    ``missing`` 是缺少或为空的字段，``invalid`` 是存在但形态不合法的
    字段。将两者分开能让前端提示“补材料”还是“修正格式”。实例的布尔
    值等于 ``complete``，因此调用方也可以直接写 ``if report``。
    """

    complete: bool
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()

    @property
    def issues(self) -> tuple[str, ...]:
        """按字段名合并缺失与非法项，保持稳定顺序且去重。"""

        return tuple(dict.fromkeys((*self.missing, *self.invalid)))

    def __bool__(self) -> bool:
        return self.complete


# 输入别名方便逐步接入旧的风险预测 DTO；输出字段仍统一使用下面的
# canonical 名称。别名只用于读取，不会改变传入 mapping。
_FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "alert_id": ("alert_id", "risk_prediction_id", "prediction_id"),
    "observation_region": (
        "observation_region",
        "observation_area",
        "region",
        "region_id",
    ),
    "prediction_window": (
        "prediction_window",
        "forecast_window",
        "window",
    ),
    "model_version": ("model_version", "risk_model_version", "analyzer_version"),
    "evidence": (
        "evidence",
        "evidence_refs",
        "evidence_ids",
        "source_evidence",
        "original_evidence",
    ),
    "status": ("status", "follow_up_status", "outcome"),
    "human_conclusion": (
        "human_conclusion",
        "conclusion",
        "reviewer_conclusion",
    ),
    "follow_up": ("follow_up", "follow_up_evidence", "followup"),
    "intervention": ("intervention", "intervention_record", "treatment"),
}

_BASE_REQUIRED: Final[tuple[str, ...]] = (
    "alert_id",
    "observation_region",
    "prediction_window",
    "model_version",
    "evidence",
    "status",
)


def _canonical_value(record: Mapping[str, Any], field: str) -> Any:
    """读取 canonical 字段或其兼容别名。"""

    for key in _FIELD_ALIASES[field]:
        if key in record:
            return record[key]
    return None


def _is_present(value: Any) -> bool:
    """判断字段是否有实际内容；数值 0 和 False 是有效值。"""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (bytes, bytearray)):
        return len(value) > 0
    return True


def _valid_prediction_window(value: Any) -> bool:
    """检查预测窗口至少表达起止边界，不强制日期类型。"""

    if isinstance(value, Mapping):
        starts = ("start", "starts_at", "from", "begin")
        ends = ("end", "ends_at", "to", "until")
        return any(_is_present(value.get(k)) for k in starts) and any(
            _is_present(value.get(k)) for k in ends
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value) == 2 and all(_is_present(v) for v in value)
    # 允许业务层传入已格式化的窗口描述，例如 "48h"，但不接受空值。
    return _is_present(value)


def validate_status(status: str | None) -> FeedbackStatus:
    """校验并返回反馈状态。

    ``None`` 不是一个可持久化状态；新记录应通过
    :func:`transition_status` 从 ``None`` 转到 ``pending``。
    """

    if status not in VALID_STATUSES:
        raise InvalidStatusError(
            f"不支持的反馈状态 {status!r}，允许值：{', '.join(sorted(VALID_STATUSES))}"
        )
    return status  # type: ignore[return-value]


def validate_transition(current: str | None, target: str) -> None:
    """校验状态转移；合法时返回 ``None``，非法时抛出明确异常。"""

    if current is not None:
        validate_status(current)
    validate_status(target)
    allowed = ALLOWED_TRANSITIONS[current]
    if target not in allowed:
        current_label = "<new>" if current is None else repr(current)
        raise InvalidTransitionError(
            f"不允许反馈状态从 {current_label} 转为 {target!r}"
        )


def transition_status(current: str | None, target: str) -> FeedbackStatus:
    """执行一次纯状态转移并返回新状态，不修改任何对象。"""

    validate_transition(current, target)
    return target  # type: ignore[return-value]


def apply_transition(record: Mapping[str, Any], target: str) -> dict[str, Any]:
    """复制反馈记录并更新状态，原 mapping 保持不变。

    该辅助函数供路由/服务层在落库前构造更新 payload；它只负责状态机，
    不会替代 :func:`check_completeness`。
    """

    if not isinstance(record, Mapping):
        raise TypeError("feedback record 必须是 mapping")
    current = _canonical_value(record, "status")
    transition_status(current, target)
    updated = dict(record)
    updated["status"] = target
    return updated


def check_completeness(
    record: Mapping[str, Any],
    *,
    require_follow_up: bool = True,
) -> CompletenessReport:
    """检查预警证据反馈记录是否足以进入审计/评估。

    基础字段是预警 ID、观察区域、预测窗口、模型版本、原始证据和状态。
    ``require_follow_up=True``（默认）时，非 ``pending`` 状态还必须有
    人工结论或随访证据；``intervened`` 另外必须记录处置，避免把受处置
    后的阴性结果误当成模型正确。函数只读输入，适合在接口和批量导出前
    重复调用。
    """

    if not isinstance(record, Mapping):
        return CompletenessReport(False, invalid=("record",))

    missing: list[str] = []
    invalid: list[str] = []

    values: dict[str, Any] = {}
    for field in _BASE_REQUIRED:
        value = _canonical_value(record, field)
        values[field] = value
        if not _is_present(value):
            missing.append(field)

    status = values["status"]
    if _is_present(status) and status not in VALID_STATUSES:
        invalid.append("status")

    if _is_present(values["prediction_window"]) and not _valid_prediction_window(
        values["prediction_window"]
    ):
        invalid.append("prediction_window")

    if not require_follow_up or status == PENDING or status not in VALID_STATUSES:
        return CompletenessReport(not missing and not invalid, tuple(missing), tuple(invalid))

    # A non-pending result needs an auditable human or follow-up conclusion.
    human_conclusion = _canonical_value(record, "human_conclusion")
    follow_up = _canonical_value(record, "follow_up")
    if not _is_present(human_conclusion) and not _is_present(follow_up):
        missing.append("human_conclusion_or_follow_up")

    if status == INTERVENED and not _is_present(_canonical_value(record, "intervention")):
        missing.append("intervention")

    return CompletenessReport(not missing and not invalid, tuple(missing), tuple(invalid))


def assert_complete(
    record: Mapping[str, Any],
    *,
    require_follow_up: bool = True,
) -> CompletenessReport:
    """完整性不通过时抛出 ``ValueError``，通过时返回报告。"""

    report = check_completeness(record, require_follow_up=require_follow_up)
    if not report.complete:
        details = ", ".join(report.issues)
        raise ValueError(f"预警证据反馈记录不完整：{details}")
    return report


# 更直观的布尔校验入口，便于调用方在提交前显示禁用状态。
def is_valid_transition(current: str | None, target: str) -> bool:
    """返回转移是否可行；未知状态也返回 ``False``。"""

    try:
        validate_transition(current, target)
    except (InvalidStatusError, InvalidTransitionError):
        return False
    return True


def is_complete(record: Mapping[str, Any], *, require_follow_up: bool = True) -> bool:
    """返回完整性布尔值的便捷包装。"""

    return check_completeness(record, require_follow_up=require_follow_up).complete
