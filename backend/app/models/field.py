"""Field 地块：边界(GeoJSON 文本)与属性（基线 B1：浮点+GeoJSON，不用 PostGIS）。"""
from typing import Any

from sqlalchemy import Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Field(TimestampMixin, Base):
    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # GeoJSON Polygon 文本（JSON 列），如 {"type":"Polygon","coordinates":[[[lng,lat],...]]}
    boundary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    area_ha: Mapped[float | None] = mapped_column(Float)
    soil_type: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    plantings: Mapped[list["Planting"]] = relationship(back_populates="field")  # type: ignore[name-defined]  # noqa: F821
