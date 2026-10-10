"""采集端设备协议 DTO：注册、心跳、事件和可控故障注入。"""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.device import DeviceBase, DeviceStatus
from app.schemas.patrol import ClockPayload, TimeWarning, warnings_or_empty


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


DeviceEventSeverity = Literal["info", "warning", "error", "critical"]


class DeviceRegisterIn(DeviceBase):
    """设备启动时的幂等注册请求。

    设备能力等扩展字段暂存于协议 payload 的边界之外；当前 Device 表只
    保存设备管理所需的稳定身份字段，避免把尚未验证的硬件能力写成事实。
    """


class DeviceHeartbeatIn(BaseModel):
    client_heartbeat_id: str | None = Field(default=None, min_length=1, max_length=120)
    observed_at: datetime = Field(default_factory=_utc_now)
    status: DeviceStatus = "idle"
    execution_phase: str = Field(default="idle", min_length=1, max_length=40)
    mission_id: int | None = Field(default=None, gt=0)
    position_source: str = Field(default="unknown", min_length=1, max_length=40)
    queue_size: int = Field(default=0, ge=0)
    battery_pct: float | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = None
    error_code: str | None = Field(default=None, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    # 车端本机时钟状态（计划 0007 P0-2，D26）
    clock: ClockPayload | None = None


class DeviceHeartbeatOut(DeviceHeartbeatIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    # 心跳时间减平台接收时间（秒）；心跳没带 observed_at 时为空
    clock_skew_s: float | None = None
    time_warnings: list[TimeWarning] = Field(default_factory=list)

    _no_null_warnings = field_validator("time_warnings", mode="before")(warnings_or_empty)
    created_at: datetime
    updated_at: datetime


class DeviceEventIn(BaseModel):
    client_event_id: str | None = Field(default=None, min_length=1, max_length=120)
    device_id: int | None = Field(default=None, gt=0)
    mission_id: int | None = Field(default=None, gt=0)
    event_type: str = Field(min_length=1, max_length=60)
    severity: DeviceEventSeverity = "info"
    source: str = Field(default="device", min_length=1, max_length=20)
    occurred_at: datetime = Field(default_factory=_utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class DeviceEventOut(DeviceEventIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_fault_injected: bool
    fault_type: str | None
    fault_active: bool | None
    created_at: datetime
    updated_at: datetime


class FaultInjectionIn(BaseModel):
    """测试用故障事件；不会声称真实硬件已经发生故障。"""

    client_event_id: str | None = Field(default=None, min_length=1, max_length=120)
    mission_id: int | None = Field(default=None, gt=0)
    fault_type: str = Field(min_length=1, max_length=80)
    active: bool = True
    severity: DeviceEventSeverity = "critical"
    occurred_at: datetime = Field(default_factory=_utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


__all__ = [
    "DeviceEventIn",
    "DeviceEventOut",
    "DeviceHeartbeatIn",
    "DeviceHeartbeatOut",
    "DeviceRegisterIn",
    "FaultInjectionIn",
    "TimeWarning",
]
