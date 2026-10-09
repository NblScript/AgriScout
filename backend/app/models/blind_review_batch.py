"""盲评批次（计划 0007 P1-9）：一个棚、一段田间日期里按种子抽出的照片，供人在看不到模型输出的情况下判读。"""
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin, UTCDateTime


class BlindReviewBatch(TimestampMixin, Base):
    __tablename__ = "blind_review_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # open 判读中 / done 全部定论
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 抽样参数留档：date_from、date_to、sample_size、reference_keys、side、double_review
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    items: Mapped[list["BlindReviewItem"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="batch", cascade="all, delete-orphan", order_by="BlindReviewItem.position",
    )
