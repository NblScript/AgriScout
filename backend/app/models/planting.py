"""Planting 种植记录：地块 × 作物 × 批次。"""
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Planting(TimestampMixin, Base):
    __tablename__ = "plantings"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"), nullable=False, index=True)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), nullable=False, index=True)
    sowing_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_harvest_date: Mapped[date | None] = mapped_column(Date)
    # active 生长期 / harvested 已收获 / archived 已归档
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    field: Mapped["Field"] = relationship(back_populates="plantings")  # type: ignore[name-defined]  # noqa: F821
    crop: Mapped["Crop"] = relationship(back_populates="plantings")  # type: ignore[name-defined]  # noqa: F821

    @property
    def field_name(self) -> str | None:
        return self.field.name if self.field else None

    @property
    def crop_name(self) -> str | None:
        return self.crop.name if self.crop else None
