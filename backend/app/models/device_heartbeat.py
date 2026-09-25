"""设备心跳：保存采集端最近一次上报及可回放的历史状态。"""
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin, UTCDateTime


class DeviceHeartbeat(TimestampMixin, Base):
    __tablename__ = "device_heartbeats"
    __table_args__ = (
        UniqueConstraint("device_id", "client_heartbeat_id", name="uq_device_heartbeat_client_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    client_heartbeat_id: Mapped[str | None] = mapped_column(String(120), index=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    execution_phase: Mapped[str] = mapped_column(String(40), nullable=False, default="idle")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("patrols.id", ondelete="SET NULL"), index=True,
    )
    position_source: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    queue_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    battery_pct: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    device: Mapped["Device"] = relationship()  # type: ignore[name-defined]
    mission: Mapped["Patrol | None"] = relationship()  # type: ignore[name-defined]
