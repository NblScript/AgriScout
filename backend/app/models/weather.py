"""WeatherSample 天气快照：挂在采样点上，同时冗余 patrol_id 便于时序聚合。"""
from sqlalchemy import Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class WeatherSample(Base):
    __tablename__ = "weather_samples"
    __table_args__ = (UniqueConstraint("capture_point_id", name="uq_weather_point"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_point_id: Mapped[int] = mapped_column(
        ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False,
    )
    patrol_id: Mapped[int] = mapped_column(
        ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # 全部可空：传感器缺测不阻断接入
    temp_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    light_lux: Mapped[float | None] = mapped_column(Float)
    wind_mps: Mapped[float | None] = mapped_column(Float)
    rain_mm: Mapped[float | None] = mapped_column(Float)
    soil_temp_c: Mapped[float | None] = mapped_column(Float)
    soil_moisture_pct: Mapped[float | None] = mapped_column(Float)

    capture_point: Mapped["CapturePoint"] = relationship(back_populates="weather")  # type: ignore[name-defined]  # noqa: F821
