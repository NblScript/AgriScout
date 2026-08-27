"""Annotation 标注 DTO。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field as PField

# 复核标签：与规则引擎的胁迫类别对齐，后续可扩展
AnnotationLabel = Literal["normal", "dry_stress", "suspected_disease", "other"]


class AnnotationCreate(BaseModel):
    label: AnnotationLabel
    annotator_name: str = PField(min_length=1, max_length=80)
    note: str | None = None


class AnnotationUpdate(BaseModel):
    label: AnnotationLabel | None = None
    annotator_name: str | None = PField(None, min_length=1, max_length=80)
    note: str | None = None


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
