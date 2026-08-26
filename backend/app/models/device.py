"""Device 载体抽象：小车/无人机/固定监测点都是数据源。"""
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # rover 巡检小车 / drone 无人机 / station 固定监测点
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    # idle 空闲 / active 作业中 / maintenance 维护 / offline 离线
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
