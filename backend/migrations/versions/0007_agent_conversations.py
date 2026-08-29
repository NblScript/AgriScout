"""M-L2 对话式诊断 Agent：agent_conversations 问答留痕表

Revision ID: 0007
Revises: 0006
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patrol_id", sa.Integer(),
                  sa.ForeignKey("patrols.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("tool_calls_trace", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_conversations_patrol_id", "agent_conversations", ["patrol_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_conversations_patrol_id", table_name="agent_conversations")
    op.drop_table("agent_conversations")
