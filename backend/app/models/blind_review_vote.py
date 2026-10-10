"""一次盲评判读：判读人取登录账号；第 1 轮两人独立判读，第 2 轮是分歧后的二次判读。"""
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class BlindReviewVote(TimestampMixin, Base):
    __tablename__ = "blind_review_votes"
    __table_args__ = (UniqueConstraint("item_id", "reviewer_user_id", name="uq_blind_vote_reviewer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("blind_review_items.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reviewer_name: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    item: Mapped["BlindReviewItem"] = relationship(back_populates="votes")  # type: ignore[name-defined]  # noqa: F821
