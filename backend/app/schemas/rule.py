"""Rule 规则 DTO。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field as PField, field_validator, model_validator

Tier = Literal["threshold", "status", "routine"]
Priority = Literal["high", "medium", "low"]

_ALLOWED_CONDITION_KEYS = {
    "stage", "vigor_level", "ndvi", "risk_score", "stress_detected", "weather",
}
_ALLOWED_WEATHER_KEYS = {
    "temp_c", "humidity_pct", "light_lux",
    "wind_mps", "rain_mm", "soil_temp_c", "soil_moisture_pct",
}
_ALLOWED_OPERATORS = {"lt", "lte", "gt", "gte", "eq", "between"}


def _validate_op_spec(spec: Any) -> None:
    if isinstance(spec, dict):
        for op, operand in spec.items():
            if op not in _ALLOWED_OPERATORS:
                raise ValueError(f"未知算子：{op}（支持 {sorted(_ALLOWED_OPERATORS)}）")
            if op == "between" and (
                not isinstance(operand, list) or len(operand) != 2
            ):
                raise ValueError("between 需要 [下限, 上限]")


def _validate_condition(condition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise ValueError("condition 必须是对象")
    for key, spec in condition.items():
        if key == "weather":
            if not isinstance(spec, dict):
                raise ValueError("condition.weather 必须是对象")
            for wf, wspec in spec.items():
                if wf not in _ALLOWED_WEATHER_KEYS:
                    raise ValueError(f"未知天气字段：{wf}")
                _validate_op_spec(wspec)
        elif key == "stage":
            if not isinstance(spec, str) or not spec:
                raise ValueError("stage 必须是非空字符串")
        elif key == "stress_detected":
            if not isinstance(spec, bool):
                raise ValueError("stress_detected 必须是布尔")
        elif key in {"vigor_level", "ndvi", "risk_score"}:
            _validate_op_spec(spec)
        else:
            raise ValueError(f"未知条件键：{key}（支持 {sorted(_ALLOWED_CONDITION_KEYS)}）")
    return condition


class RuleBase(BaseModel):
    rule_key: str = PField(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_.]*$")
    crop_id: int | None = None
    tier: Tier
    condition: dict[str, Any] = {}
    action: str = PField(min_length=2)
    params: dict[str, Any] | None = None
    priority: Priority = "medium"
    source: str | None = None

    @field_validator("condition")
    @classmethod
    def check_condition(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_condition(v)

    @model_validator(mode="after")
    def tier_condition_consistency(self) -> "RuleBase":
        if self.tier == "routine":
            # 常规层是保底：仅允许按生育期定向（日历法必然可算），不得依赖分析/天气数据
            illegal = set(self.condition) - {"stage"}
            if illegal:
                raise ValueError(f"routine 层仅允许 stage 条件，发现非法键：{sorted(illegal)}")
        elif not self.condition:
            raise ValueError(f"{self.tier} 层规则必须至少有一个条件")
        return self


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    tier: Tier | None = None
    condition: dict[str, Any] | None = None
    action: str | None = PField(default=None, min_length=2)
    params: dict[str, Any] | None = None
    priority: Priority | None = None
    active: bool | None = None
    source: str | None = None

    @field_validator("condition")
    @classmethod
    def check_condition(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if v is None else _validate_condition(v)


class RuleOut(RuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime
