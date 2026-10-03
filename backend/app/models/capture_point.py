"""CapturePoint 采样点：每个采样间距（候选 0.5 m）一个点，系统的一等公民（基线 B1：lng/lat 浮点双列）。"""
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin, UTCDateTime


class CapturePoint(TimestampMixin, Base):
    __tablename__ = "capture_points"
    __table_args__ = (UniqueConstraint("patrol_id", "seq", name="uq_capture_patrol_seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patrol_id: Mapped[int] = mapped_column(
        ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 包内序号，从 0/1 均可
    distance_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(500))  # 本地 /media/... 或外部 URL；照片不进库
    # 协议 v2 最小子集（计划 0014）：株号、行内位置、距离/定位来源、视角元数据
    observation_key: Mapped[str | None] = mapped_column(String(80), index=True)
    observation_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("observation_units.id", ondelete="SET NULL"), index=True,
    )
    route_chainage_m: Mapped[float | None] = mapped_column(Float)
    distance_source: Mapped[str | None] = mapped_column(String(20))
    position_source: Mapped[str | None] = mapped_column(String(20))
    # 协议字段名是 view，列名避开 SQL 关键字
    view_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    patrol: Mapped["Patrol"] = relationship(back_populates="capture_points")  # type: ignore[name-defined]  # noqa: F821
    weather: Mapped["WeatherSample | None"] = relationship(
        back_populates="capture_point", uselist=False,
        cascade="all, delete-orphan", passive_deletes=True,
    )
    analysis: Mapped["Analysis | None"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="capture_point", uselist=False,
        cascade="all, delete-orphan", passive_deletes=True,
    )
