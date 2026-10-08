"""棚内环境读数、每株状态、巡检计划 DTO（计划 0015）。"""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EnvSource = Literal["sensor", "import", "manual"]
SENSOR_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,39}$"
MAX_READINGS_PER_UPLOAD = 5000


class EnvReadingIn(BaseModel):
    # 不带时区的时间按 UTC 解释（D9）；记录仪导出的本地时间请在采集端换算或带上时区
    observed_at: datetime
    temp_c: float = Field(ge=-40, le=70)
    humidity_pct: float = Field(ge=0, le=100)
    leaf_wetness: float | None = Field(default=None, ge=0, le=1)


class EnvUploadIn(BaseModel):
    sensor_key: str = Field(pattern=SENSOR_KEY_PATTERN, description="记录仪编号或安装位置")
    device: str | None = Field(default=None, min_length=1, max_length=50, description="已登记设备的 code（可选）")
    source: EnvSource = "sensor"
    readings: list[EnvReadingIn] = Field(min_length=1, max_length=MAX_READINGS_PER_UPLOAD)


class EnvUploadOut(BaseModel):
    inserted: int
    skipped: int  # 同一传感器同一时刻已存在（含本次请求里的重复）


class EnvHourOut(BaseModel):
    hour: datetime
    count: int
    missing: bool
    temp_c: float | None
    humidity_pct: float | None
    dewpoint_depression_min: float | None
    leaf_wetness_max: float | None
    favorable: bool
    wet: bool


class EnvDayOut(BaseModel):
    field_date: date
    favorable_hours: int
    wet_hours: int
    night_wet_hours: int
    night_coverage: float
    diurnal_range: float | None
    coverage: float


class EnvIndexOut(BaseModel):
    method: str
    env_index: float | None  # None = 覆盖率不足，按无环境信息处理（不是低风险）
    as_of: datetime
    window_hours: int
    favorable_hours: int
    wet_hours: int
    coverage: float
    reason: str | None = None


class MorningWindowOut(BaseModel):
    date: date
    start: str
    end: str
    night_of: date
    night_wet_hours: int
    reason: str


class EnvSummaryOut(BaseModel):
    field_id: int
    since: datetime
    until: datetime
    sensors: list[str]
    hourly: list[EnvHourOut]
    daily: list[EnvDayOut]
    index: EnvIndexOut
    morning_window: MorningWindowOut | None
    params: dict[str, Any]


class PlantStateOut(BaseModel):
    unit_id: int
    key: str
    row_no: int | None
    position_no: int | None
    state: Literal["healthy", "early", "symptomatic", "unknown"]
    source: Literal["human", "model", "none"]
    confidence: float
    model_score: float | None
    last_seen_at: datetime | None
    last_under_ok_at: datetime | None
    last_under_accepted: bool | None
    reviewed_at: datetime | None
    analyzer_version: str | None


class PatrolPlanIn(BaseModel):
    plan_date: date | None = Field(default=None, description="计划日（田间日期），默认今天")
    overrides: dict[str, float] | None = Field(default=None, description="覆盖巡检计划 PlannerParams 的数值参数")
    created_by: str = Field(default="system", min_length=1, max_length=80)


class PlanItemOut(BaseModel):
    unit_id: int
    key: str
    row_no: int | None = None
    position_no: int | None = None
    list_name: Literal["confirm", "reshoot", "coverage", "random"]
    task_id: int
    task_type: str
    task_status: str
    score: float
    priority: float
    rationale: dict[str, Any]


class PatrolPlanOut(BaseModel):
    field_id: int
    plan_version: str
    plan_date: date
    generation: int | None = None  # 本地块第几次生成计划
    generated_at: datetime | None = None
    seed: str
    units: int
    reshoot_budget: int
    env: dict[str, Any]
    window: MorningWindowOut | None
    confirm: list[PlanItemOut]
    reshoot: list[PlanItemOut]
    coverage: list[PlanItemOut]
    random: list[PlanItemOut]
    params: dict[str, Any] | None = None  # 只在生成时返回；取最近计划时只有任务里存的部分
