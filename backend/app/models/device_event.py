"""设备和任务事件：包括可重复回放的安全事件与故障注入事件。"""
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class DeviceEvent(TimestampMixin, Base):
    __tablename__ = "device_events"
    __table_args__ = (
        UniqueConstraint("device_id", "client_event_id", name="uq_device_event_client_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), index=True,
    )
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("patrols.id", ondelete="SET NULL"), index=True,
    )
    client_event_id: Mapped[str | None] = mapped_column(String(120), index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="device")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_fault_injected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fault_type: Mapped[str | None] = mapped_column(String(80))
    fault_active: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text)

    device: Mapped["Device | None"] = relationship()  # type: ignore[name-defined]
    mission: Mapped["Patrol | None"] = relationship()  # type: ignore[name-defined]
