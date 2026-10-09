"""盲评批次里的一张照片：判读状态、定论和写出的标注。"""
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin, UTCDateTime


class BlindReviewItem(TimestampMixin, Base):
    __tablename__ = "blind_review_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "capture_point_id", name="uq_blind_item_point"),
        UniqueConstraint("batch_id", "position", name="uq_blind_item_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("blind_review_batches.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    capture_point_id: Mapped[int] = mapped_column(
        ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # 打乱后的判读顺序，从 1 开始
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # random 随机抽查 / reference 固定参考株；判读时不显示
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    # pending 未判 / partial 一人判过 / agreed 两人一致 / disputed 待二次判读 / adjudicated 二次判读定论
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    final_label: Mapped[str | None] = mapped_column(String(50))
    annotation_id: Mapped[int | None] = mapped_column(ForeignKey("annotations.id", ondelete="SET NULL"), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    batch: Mapped["BlindReviewBatch"] = relationship(back_populates="items")  # type: ignore[name-defined]  # noqa: F821
    capture_point: Mapped["CapturePoint"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    votes: Mapped[list["BlindReviewVote"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="item", cascade="all, delete-orphan", order_by="BlindReviewVote.id",
    )
