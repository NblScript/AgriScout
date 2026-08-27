"""Annotation 人工标注：复核结果落库形成数据集，反哺后续模型训练（回流闭环）。"""
from typing import Any

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class Annotation(TimestampMixin, Base):
    __tablename__ = "annotations"
    # 一点一标签只保留一条复核结论；updated_at 即最近复核时间
    __table_args__ = (UniqueConstraint("capture_point_id", "label", name="uq_annotation_point_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_point_id: Mapped[int] = mapped_column(
        ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # 冗余巡检外键：整包查询/导出免联表
    patrol_id: Mapped[int] = mapped_column(
        ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # normal 正常 / dry_stress 干旱胁迫 / suspected_disease 疑似病害 / other 其他
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    # 认证已砍除（基线 B4），以姓名归属标注人
    annotator_name: Mapped[str] = mapped_column(String(80), nullable=False)
    # 预留：归一化 [x, y, w, h]，供后续画框产出 YOLO 训练格式
    bbox: Mapped[list[Any] | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)

    capture_point: Mapped["CapturePoint"] = relationship()  # type: ignore[name-defined]  # noqa: F821
