"""RuleRevision 规则修订案：规则线 L1 的起草-审批载体。

Agent 只有起草权：draft JSON 经影子运行 + 人工批准后才由系统写入规则表
（version+1，走 sync_rules 同款指纹比对）。驳回的修订案归档留痕不删除。
"""
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class RuleRevision(TimestampMixin, Base):
    __tablename__ = "rule_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # 修订类型：modify 改现有 / add 新增 / deactivate 停用
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    # 起草的完整规则字段（action=modify/deactivate 时为改动后形态）
    draft: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # 起草理由（引用燃料数据）
    # 影子运行 diff：{patrols_checked, advices_before, advices_after, added, removed, per_patrol:[...]}
    shadow_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # draft 待审 / approved 已生效 / rejected 已驳回
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    # 审批留痕
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decide_note: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # 批准后回填
    applied_version: Mapped[int | None] = mapped_column()
