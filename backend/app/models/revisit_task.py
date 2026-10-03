"""复巡和主动学习任务：统一承载补拍、标注和随机抽查。"""
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin, UTCDateTime


class RevisitTask(TimestampMixin, Base):
    __tablename__ = "revisit_tasks"
    __table_args__ = (UniqueConstraint("risk_prediction_id", name="uq_revisit_task_prediction"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True)
    patrol_id: Mapped[int | None] = mapped_column(ForeignKey("patrols.id", ondelete="SET NULL"), index=True)
    capture_point_id: Mapped[int | None] = mapped_column(ForeignKey("capture_points.id", ondelete="SET NULL"), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    risk_prediction_id: Mapped[int | None] = mapped_column(
        ForeignKey("risk_predictions.id", ondelete="SET NULL"), index=True,
    )
    # 计划 0015：巡检计划的任务落到株上（同株每种类型只保留一条未完成任务）
    observation_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("observation_units.id", ondelete="SET NULL"), index=True,
    )
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)  # revisit / label / random / coverage
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    value_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result_note: Mapped[str | None] = mapped_column(Text)

    field: Mapped["Field"] = relationship()  # type: ignore[name-defined]
    patrol: Mapped["Patrol | None"] = relationship()  # type: ignore[name-defined]
    capture_point: Mapped["CapturePoint | None"] = relationship()  # type: ignore[name-defined]
    device: Mapped["Device | None"] = relationship()  # type: ignore[name-defined]
    risk_prediction: Mapped["RiskPrediction | None"] = relationship()  # type: ignore[name-defined]
    observation_unit: Mapped["ObservationUnit | None"] = relationship()  # type: ignore[name-defined]
