"""Advice 农事建议：规则引擎产出，冻结命中时刻的规则快照保证历史永远可追溯。"""
from typing import Any

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Advice(TimestampMixin, Base):
    __tablename__ = "advices"

    id: Mapped[int] = mapped_column(primary_key=True)
    patrol_id: Mapped[int] = mapped_column(
        ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    capture_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("capture_points.id", ondelete="CASCADE"), index=True,
    )
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"))  # 软删除策略下不级联
    rule_key: Mapped[str] = mapped_column(String(80), nullable=False)  # 冗余键便于统计
    # 冻结命中时刻的 {rule_key,tier,priority,condition,action,params,source,version}
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    # suggested 待处理 / accepted 已采纳 / rejected 已驳回
    status: Mapped[str] = mapped_column(String(20), default="suggested", nullable=False)

    capture_point: Mapped["CapturePoint | None"] = relationship()  # type: ignore[name-defined]  # noqa: F821
    rule: Mapped["Rule | None"] = relationship()  # type: ignore[name-defined]  # noqa: F821
