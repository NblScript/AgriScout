"""Analysis 每采样点评估结果：M3 占位算法产出，未来 YOLO 同表同接口替换。"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_point_id: Mapped[int] = mapped_column(
        ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False, unique=True,
    )
    patrol_id: Mapped[int] = mapped_column(
        ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # 如 placeholder-color-v0 → 未来 yolo8n-v1；升级只换版本号，历史保留
    analyzer_version: Mapped[str] = mapped_column(String(50), nullable=False)
    # 生育期概率分布 {"name":..,"probability":..,"source":"calendar"}（占位=日历法）
    growth_stage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    vigor_level: Mapped[int | None] = mapped_column(Integer)  # 1-5，5 最旺
    # ⚠️ 占位实现为绿色覆盖率代理值，非真实 NDVI（真实需 NIR 传感/多光谱）
    ndvi: Mapped[float | None] = mapped_column(Float)
    disease_detections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    risk_score: Mapped[float | None] = mapped_column(Float)  # 0-1
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # 原始指标：绿色占比等
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    capture_point: Mapped["CapturePoint"] = relationship(back_populates="analysis")  # type: ignore[name-defined]  # noqa: F821
