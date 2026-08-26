"""Advice 建议 DTO。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field as PField

AdviceStatus = Literal["suggested", "accepted", "rejected"]


class AdviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patrol_id: int
    capture_point_id: int | None = None
    rule_id: int | None = None
    rule_key: str
    rule_snapshot: dict[str, Any]
    content: str
    priority: str
    status: str
    created_at: datetime


class AdviceStatusUpdate(BaseModel):
    status: AdviceStatus
    note: str | None = None


class GenerateAdvicesOut(BaseModel):
    patrol_id: int
    created: int
    deleted_suggested: int
    skipped_decided: int
    points: int
    rules_active: int
