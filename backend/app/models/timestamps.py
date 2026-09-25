"""ORM 模型公共混入与公共列类型。"""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.core.timeutil import to_utc


class UTCDateTime(TypeDecorator):
    """带时区时间列：写入前换算为 UTC，读回一律带 UTC 时区（决策 D9）。

    SQLite 存 DateTime 会直接丢弃时区、不做换算，东八区与 UTC 墙钟混存后无法比较；
    统一在数据库边界换算，业务代码拿到的永远是可比较的 aware 时间。DDL 与原
    ``DateTime(timezone=True)`` 相同，无需迁移。
    """

    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = to_utc(value)
        # SQLite 无时区概念：显式存 UTC 墙钟，读回时再补 UTC
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        return None if value is None else to_utc(value)


class TimestampMixin:
    """created_at / updated_at 审计字段。"""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )
