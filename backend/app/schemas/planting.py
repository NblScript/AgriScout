"""Planting 种植记录 DTO。"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field as PField

PlantingStatus = Literal["active", "harvested", "archived"]


class PlantingBase(BaseModel):
    field_id: int = PField(gt=0)
    crop_id: int = PField(gt=0)
    sowing_date: date
    expected_harvest_date: date | None = None
    status: PlantingStatus = "active"
    notes: str | None = None


class PlantingCreate(PlantingBase):
    pass


class PlantingUpdate(BaseModel):
    sowing_date: date | None = None
    expected_harvest_date: date | None = None
    status: PlantingStatus | None = None
    notes: str | None = None


class PlantingOut(PlantingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_name: str | None = None
    crop_name: str | None = None
    created_at: datetime
    updated_at: datetime
