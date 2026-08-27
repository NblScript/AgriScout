"""PatrolReport 巡检 AI 农事报告：建议线 L1——规则兜底 + LLM 解释层。

LLM 基于分析摘要与规则命中结果生成巡检级农事报告；可溯源（model/prompt_version/
input_digest 冻结）；一巡检一报告（unique upsert）；不写规则表（决策红线）。
"""
from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class PatrolReport(TimestampMixin, Base):
    __tablename__ = "patrol_reports"
    __table_args__ = (UniqueConstraint("patrol_id", name="uq_report_patrol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patrol_id: Mapped[int] = mapped_column(
        ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)  # markdown
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # 输入摘要快照：分析摘要/命中规则 keys/天气概况——报告可复现的依据
    input_digest: Mapped[dict] = mapped_column(JSON, nullable=False)
