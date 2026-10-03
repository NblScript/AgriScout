"""Annotation 标注 DTO。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field as PField, model_validator

from app.schemas.common import reject_explicit_nulls

# 复核标签：normal / dry_stress / suspected_disease 与小麦规则引擎的胁迫类别对齐；
# downy_mildew_early / downy_mildew_symptomatic 是黄瓜霜霉病「早期 / 明显」确认（计划 0015，口径见 0013），
# 只进每株状态，不参与小麦规则的漏报统计（rule_feedback.STRESS_LABELS 不含它们）
AnnotationLabel = Literal[
    "normal", "dry_stress", "suspected_disease", "other", "downy_mildew_early", "downy_mildew_symptomatic",
]


class AnnotationCreate(BaseModel):
    label: AnnotationLabel
    annotator_name: str = PField(min_length=1, max_length=80)
    note: str | None = None


class AnnotationUpdate(BaseModel):
    label: AnnotationLabel | None = None
    annotator_name: str | None = PField(None, min_length=1, max_length=80)
    note: str | None = None

    @model_validator(mode="after")
    def _no_null_required(self) -> "AnnotationUpdate":
        reject_explicit_nulls(self, ("label", "annotator_name"))
        return self


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patrol_id: int
    capture_point_id: int
    label: str
    annotator_name: str
    bbox: list[Any] | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class PatrolAnnotationSummary(BaseModel):
    """回放页进度徽标用：总点数 / 已复核点数（去重）/ 标注条数。"""

    patrol_id: int
    points_total: int
    annotated_points: int
    annotations_total: int
