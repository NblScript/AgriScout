"""EnvReading 棚内环境读数：温湿度记录仪的连续时序（计划 0015，创新点三的环境输入）。

与挂在采样点上的 ``WeatherSample``（巡检时刻快照）不同，这里是按传感器连续记录、与巡检无关的时序。
同一传感器同一时刻只存一条，重复上报跳过。
"""
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.timestamps import UTCDateTime


class EnvReading(Base):
    __tablename__ = "env_readings"
    __table_args__ = (
        UniqueConstraint("field_id", "sensor_key", "observed_at", name="uq_env_reading_sensor_time"),
        Index("ix_env_readings_field_time", "field_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    sensor_key: Mapped[str] = mapped_column(String(40), nullable=False)  # 记录仪编号或安装位置
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    temp_c: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)  # 0–100
    leaf_wetness: Mapped[float | None] = mapped_column(Float)  # 0–1，没有叶面湿度传感器时为空
    # sensor 记录仪上报 / import 导入历史文件 / manual 人工录入
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="sensor")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now(), nullable=False)
