"""Crop 作物：生命周期参数（首批作物=小麦，基线 B3）。"""
from typing import Any

from sqlalchemy import Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Crop(TimestampMixin, Base):
    __tablename__ = "crops"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    variety: Mapped[str | None] = mapped_column(String(100))
    lifecycle_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # 各生育期天数 [{"name":"出苗期","days":15},...]，顺序即生长顺序
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # M4 规则库启用前的预留位
    default_rules: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)

    plantings: Mapped[list["Planting"]] = relationship(back_populates="crop")  # type: ignore[name-defined]  # noqa: F821
