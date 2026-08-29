"""M-L1 规则起草 Agent：rule_revisions 修订案表

Revision ID: 0008
Revises: 0007
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("shadow_result", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("decided_by", sa.String(length=80), nullable=True),
        sa.Column("decide_note", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("applied_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rule_revisions_rule_key", "rule_revisions", ["rule_key"])


def downgrade() -> None:
    op.drop_index("ix_rule_revisions_rule_key", table_name="rule_revisions")
    op.drop_table("rule_revisions")
