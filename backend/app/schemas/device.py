"""Device 载体 DTO。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field as PField

DeviceType = Literal["rover", "drone", "station"]
DeviceStatus = Literal["idle", "active", "maintenance", "offline"]


class DeviceBase(BaseModel):
    code: str = PField(min_length=1, max_length=50)
    name: str = PField(min_length=1, max_length=100)
    type: DeviceType
    model: str | None = None
    status: DeviceStatus = "idle"
    notes: str | None = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: str | None = PField(default=None, min_length=1, max_length=100)
    type: DeviceType | None = None
    model: str | None = None
    status: DeviceStatus | None = None
    notes: str | None = None


class DeviceOut(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
