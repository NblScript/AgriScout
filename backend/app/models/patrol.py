"""Patrol 巡检任务：一次巡检 + 轨迹（基线 B1：GeoJSON 文本存储）。"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Patrol(TimestampMixin, Base):
    __tablename__ = "patrols"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"), nullable=False, index=True)
    planting_id: Mapped[int | None] = mapped_column(ForeignKey("plantings.id"), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # GeoJSON LineString：{"type":"LineString","coordinates":[[lng,lat],...]}
    track: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # planned 已计划 / received 数据已接入 / completed 已完成
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    # pending / running / done / error（M3 分析管线驱动）
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    field: Mapped["Field"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    device: Mapped["Device"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    capture_points: Mapped[list["CapturePoint"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="patrol", cascade="all, delete-orphan", passive_deletes=True,
        order_by="CapturePoint.seq",
    )

    @property
    def field_name(self) -> str | None:
        return self.field.name if self.field else None

    @property
    def device_code(self) -> str | None:
        return self.device.code if self.device else None

    @property
    def point_count(self) -> int:
        return len(self.capture_points)
