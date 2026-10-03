"""株档案与单株时间线 DTO（计划 0014）。"""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import reject_explicit_nulls
from app.schemas.patrol import OBSERVATION_KEY_PATTERN

UnitStatus = Literal["active", "retired"]
UnitSource = Literal["manual", "bulk", "ingest"]


class ObservationUnitCreate(BaseModel):
    key: str = Field(pattern=OBSERVATION_KEY_PATTERN, description="株号；推荐 R{垄号两位}-P{株序号三位}")
    chainage_m: float | None = Field(default=None, ge=0)
    tag_code: str | None = Field(default=None, pattern=OBSERVATION_KEY_PATTERN)
    note: str | None = None


class ObservationUnitUpdate(BaseModel):
    tag_code: str | None = Field(default=None, pattern=OBSERVATION_KEY_PATTERN)
    status: UnitStatus | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _no_null_status(self) -> "ObservationUnitUpdate":
        reject_explicit_nulls(self, ("status",))
        return self


class ObservationUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_id: int
    key: str
    row_no: int | None = None
    position_no: int | None = None
    chainage_m: float | None = None
    tag_code: str | None = None
    status: str
    created_from: str
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class BulkRowIn(BaseModel):
    row_no: int = Field(ge=1, le=99, description="垄号（推荐格式两位）")
    plants: int = Field(ge=1, le=999, description="这一垄的株数（推荐格式三位）")
    spacing_m: float = Field(gt=0, le=10, description="株距（米）")
    start_chainage_m: float = Field(default=0.0, ge=0, description="第 1 株的行内位置（米）")


class BulkCreateIn(BaseModel):
    rows: list[BulkRowIn] = Field(min_length=1)


class BulkCreateOut(BaseModel):
    created: int
    skipped: int


class TimelineAnalysis(BaseModel):
    risk_score: float | None = None
    disease_detections: list[dict[str, Any]] | None = None
    analyzer_version: str
    image_quality: dict[str, Any] | None = None  # 0016-A 起分析结果里才有


class TimelinePhoto(BaseModel):
    capture_point_id: int
    patrol_id: int
    captured_at: datetime
    photo_url: str | None = None
    view: dict[str, Any] | None = None
    analysis: TimelineAnalysis | None = None


class TimelineAnnotation(BaseModel):
    id: int
    capture_point_id: int
    label: str
    annotator_name: str
    note: str | None = None
    updated_at: datetime


class TimelinePrediction(BaseModel):
    id: int
    capture_point_id: int | None = None
    target_event: str
    model_version: str
    probability: float
    level: str
    trend: str
    status: str
    follow_up_status: str | None = None


class TimelineDay(BaseModel):
    field_date: date
    photos: list[TimelinePhoto]
    annotations: list[TimelineAnnotation]
    predictions: list[TimelinePrediction]


class UnitTimelineOut(BaseModel):
    unit: ObservationUnitOut
    days: list[TimelineDay]
