"""风险预测的后续核查和处置记录。"""
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class FollowUp(TimestampMixin, Base):
    __tablename__ = "risk_follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    risk_prediction_id: Mapped[int] = mapped_column(
        ForeignKey("risk_predictions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intervention_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)

    prediction: Mapped["RiskPrediction"] = relationship(back_populates="follow_up")  # type: ignore[name-defined]
