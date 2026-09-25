"""申报书软件闭环的 API DTO。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import reject_explicit_nulls


RiskLevel = Literal["low", "medium", "high", "unknown"]
TaskType = Literal["revisit", "label", "random"]
TaskStatus = Literal["queued", "assigned", "running", "completed", "cancelled"]
FollowUpStatus = Literal[
    "pending", "confirmed_positive", "confirmed_negative", "insufficient", "intervened", "unknown",
]


class RiskPredictionCreate(BaseModel):
    patrol_id: int = Field(gt=0)
    capture_point_id: int | None = Field(default=None, gt=0)
    observation_key: str = Field(min_length=1, max_length=160)
    target_event: str = Field(min_length=1, max_length=120)
    forecast_hours: int = Field(gt=0, le=24 * 365)
    forecast_start: datetime
    forecast_end: datetime
    probability: float = Field(ge=0, le=1)
    level: RiskLevel
    trend: str = Field(default="stable", min_length=1, max_length=20)
    confidence: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1, max_length=80)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RiskPredictionOut(RiskPredictionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    updated_at: datetime


class RiskGenerateIn(BaseModel):
    target_event: str = Field(min_length=1, max_length=120)
    forecast_hours: int = Field(default=48, gt=0, le=24 * 365)
    # v2：区域级输入 + 历史巡检（计划 0008）；v1 为逐点单次观测，旧结果按版本号区分
    model_version: str = Field(default="risk-heuristic-v2", min_length=1, max_length=80)
    region_cell_m: float = Field(default=2.5, gt=0, le=50, description="区域关联 grid-v0 的网格边长（米）")
    history_days: int = Field(default=30, ge=0, le=365, description="回看多少天内的历史巡检")


class FollowUpIn(BaseModel):
    status: FollowUpStatus
    reviewed_by: str = Field(min_length=1, max_length=80)
    event_confirmed: bool | None = None
    event_at: datetime | None = None
    intervention_at: datetime | None = None
    evidence: dict[str, Any] | None = None
    note: str | None = None


class FollowUpOut(FollowUpIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    risk_prediction_id: int
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RevisitTaskCreate(BaseModel):
    field_id: int = Field(gt=0)
    patrol_id: int | None = Field(default=None, gt=0)
    capture_point_id: int | None = Field(default=None, gt=0)
    device_id: int | None = Field(default=None, gt=0)
    risk_prediction_id: int | None = Field(default=None, gt=0)
    task_type: TaskType
    priority: float = Field(ge=0, le=1)
    value_score: float = Field(ge=0, le=1)
    rationale: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(default="system", min_length=1, max_length=80)
    scheduled_at: datetime | None = None


class RevisitTaskUpdate(BaseModel):
    status: TaskStatus | None = None
    device_id: int | None = Field(default=None, gt=0)
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    result_note: str | None = None

    @model_validator(mode="after")
    def _no_null_required(self) -> "RevisitTaskUpdate":
        reject_explicit_nulls(self, ("status",))
        return self


class RevisitTaskOut(RevisitTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    completed_at: datetime | None
    result_note: str | None
    created_at: datetime
    updated_at: datetime


class TaskGenerateIn(BaseModel):
    field_id: int = Field(gt=0)
    patrol_id: int | None = Field(default=None, gt=0)
    limit: int = Field(default=20, ge=1, le=200)
    created_by: str = Field(default="system", min_length=1, max_length=80)


class DatasetVersionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    source_filter: dict[str, Any] = Field(default_factory=dict)
    label_schema: dict[str, Any] = Field(default_factory=dict)
    row_count: int = Field(default=0, ge=0)
    created_by: str = Field(default="system", min_length=1, max_length=80)


class DatasetVersionOut(DatasetVersionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    frozen_at: datetime | None
    snapshot_sha256: str | None
    snapshot_summary: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class DatasetFreezeIn(BaseModel):
    # 兼容旧客户端字段；服务端冻结时始终按实际标注快照计算行数。
    row_count: int | None = Field(default=None, ge=0)


class ModelEvaluationCreate(BaseModel):
    dataset_version_id: int | None = Field(default=None, gt=0)
    model_name: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=80)
    split: str = Field(default="test", min_length=1, max_length=20)
    metrics: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    evaluated_at: datetime


class ModelEvaluationOut(ModelEvaluationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelApproveIn(BaseModel):
    approved_by: str = Field(min_length=1, max_length=80)
