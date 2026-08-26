"""Patrol / CapturePoint 查询侧 DTO。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.patrol import WeatherPayload


class WeatherOut(WeatherPayload):
    model_config = ConfigDict(from_attributes=True)


class CapturePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patrol_id: int
    seq: int
    distance_m: float
    lng: float
    lat: float
    captured_at: datetime
    photo_url: str | None = None
    weather: WeatherOut | None = None


class PatrolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_id: int
    field_name: str | None = None
    planting_id: int | None = None
    device_id: int | None = None
    device_code: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    analysis_status: str


class PatrolDetailOut(PatrolOut):
    track: dict[str, Any] | None = None
    point_count: int
    notes: str | None = None
