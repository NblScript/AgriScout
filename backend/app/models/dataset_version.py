"""冻结的数据集版本：记录来源、标签规范和分区。"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class DatasetVersion(TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_dataset_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    source_filter: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    label_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 冻结后保存确定性的 NDJSON 快照；行内只保留照片 URL，不把照片二进制写入数据库。
    snapshot_ndjson: Mapped[str | None] = mapped_column(Text)
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    snapshot_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="system")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evaluations: Mapped[list["ModelEvaluation"]] = relationship(  # type: ignore[name-defined]
        back_populates="dataset", cascade="all, delete-orphan",
    )
