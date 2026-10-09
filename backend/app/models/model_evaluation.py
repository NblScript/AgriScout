"""模型评估与发布闸门记录。"""
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin, UTCDateTime


class ModelEvaluation(TimestampMixin, Base):
    __tablename__ = "model_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="SET NULL"), index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    split: Mapped[str] = mapped_column(String(20), nullable=False, default="test")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 计划 0007 P1-7（D24）：逐条预测 [{annotation_id, score}]，平台对照冻结快照重算的指标；审批只认后者
    predictions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    platform_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    notes: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    dataset: Mapped["DatasetVersion | None"] = relationship(back_populates="evaluations")  # type: ignore[name-defined]
