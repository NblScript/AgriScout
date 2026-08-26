"""Rule 规则库：YAML 为源、Rule 表为运行时副本（docs/05 生命周期）。"""
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Rule(TimestampMixin, Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # null = 作物无关规则；有值则仅该作物的巡检命中
    crop_id: Mapped[int | None] = mapped_column(ForeignKey("crops.id"), index=True)
    # threshold 天气阈值 / status 分析状态 / routine 生育期常规保底
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # action 模板插值参数
    priority: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)  # high/medium/low
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 内容变更自增，进快照
    source: Mapped[str | None] = mapped_column(String(300))  # 农艺出处（答辩可溯）

    crop: Mapped["Crop | None"] = relationship()  # type: ignore[name-defined]  # noqa: F821
