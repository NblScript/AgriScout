"""ObservationUnit 株档案：同株时序追踪的落点（计划 0014，创新点二的地基）。

株号 ``key`` 即标签里的字符串。推荐格式 ``R{垄号两位}-P{株序号三位}``（如 R03-P017），
能解析出垄号和株序号，邻株特征按 (垄, 株) 的 8 邻域计算；自定义键两者为空、没有邻株。
"""
from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class ObservationUnit(TimestampMixin, Base):
    __tablename__ = "observation_units"
    __table_args__ = (
        UniqueConstraint("field_id", "key", name="uq_observation_unit_key"),
        UniqueConstraint("field_id", "tag_code", name="uq_observation_unit_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    row_no: Mapped[int | None] = mapped_column(Integer)
    position_no: Mapped[int | None] = mapped_column(Integer)
    chainage_m: Mapped[float | None] = mapped_column(Float)  # 标称行内位置（米）
    tag_code: Mapped[str | None] = mapped_column(String(80))
    # active 在册 / retired 拔除或停用
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # manual 单株手建 / bulk 批量建档 / ingest 上传时自动建（待人工核对）
    created_from: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    note: Mapped[str | None] = mapped_column(Text)
