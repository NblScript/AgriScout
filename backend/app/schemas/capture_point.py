"""Patrol / CapturePoint 查询侧 DTO。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import AnalysisOut
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
    analysis: AnalysisOut | None = None
    # 协议 v2 最小子集（计划 0014）；v1 包这些字段为空
    observation_key: str | None = None
    observation_unit_id: int | None = None
    route_chainage_m: float | None = None
    distance_source: str | None = None
    position_source: str | None = None
    view: dict[str, Any] | None = Field(default=None, validation_alias="view_meta")


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
    schema_version: str = "1.0"
    client_package_id: str | None = None
    point_count: int
    notes: str | None = None
