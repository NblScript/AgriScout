"""Crop 作物 DTO。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field as PField, model_validator

from app.schemas.common import reject_explicit_nulls


class StageItem(BaseModel):
    """单个生育期：名称 + 持续天数。"""

    name: str = PField(min_length=1)
    days: int = PField(ge=1)


class CropBase(BaseModel):
    name: str = PField(min_length=1, max_length=100)
    variety: str | None = None
    lifecycle_days: int = PField(ge=1)
    stages: list[StageItem] = []
    description: str | None = None


class CropCreate(CropBase):
    pass


class CropUpdate(BaseModel):
    name: str | None = PField(default=None, min_length=1, max_length=100)
    variety: str | None = None
    lifecycle_days: int | None = PField(default=None, ge=1)
    stages: list[StageItem] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _no_null_required(self) -> "CropUpdate":
        reject_explicit_nulls(self, ("name", "lifecycle_days", "stages"))
        return self


class CropOut(CropBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    default_rules: list[dict[str, Any]] | None = None
    created_at: datetime
    updated_at: datetime
