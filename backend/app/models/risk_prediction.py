"""区域级风险预测：保存可复核的预测窗口、证据和模型版本。"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class RiskPrediction(TimestampMixin, Base):
    __tablename__ = "risk_predictions"
    __table_args__ = (
        UniqueConstraint(
            "patrol_id", "capture_point_id", "target_event", "forecast_start",
            "forecast_hours", "model_version", name="uq_risk_prediction_window",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patrol_id: Mapped[int] = mapped_column(ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True)
    capture_point_id: Mapped[int | None] = mapped_column(ForeignKey("capture_points.id", ondelete="SET NULL"), index=True)
    observation_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    target_event: Mapped[str] = mapped_column(String(120), nullable=False)
    forecast_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    trend: Mapped[str] = mapped_column(String(20), nullable=False, default="stable")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")

    patrol: Mapped["Patrol"] = relationship()  # type: ignore[name-defined]
    capture_point: Mapped["CapturePoint | None"] = relationship()  # type: ignore[name-defined]
    follow_up: Mapped["FollowUp | None"] = relationship(  # type: ignore[name-defined]
        back_populates="prediction", uselist=False, cascade="all, delete-orphan",
    )
