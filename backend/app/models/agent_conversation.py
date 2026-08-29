"""AgentConversation 诊断问答留痕：建议线 L2 的溯源载体。

每问一行（重问追加新行）；tool_calls_trace 冻结 Agent 用了哪些工具什么参数，
回答可复现可审计。patrol_id 可空（全局问询不挂巡检）。
"""
from typing import Any

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.timestamps import TimestampMixin


class AgentConversation(TimestampMixin, Base):
    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    patrol_id: Mapped[int | None] = mapped_column(
        ForeignKey("patrols.id", ondelete="SET NULL"), index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls_trace: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
