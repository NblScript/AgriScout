"""M-L1 建议线 L1：patrol_reports 巡检 AI 农事报告表

Revision ID: 0006
Revises: 0005
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patrol_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "patrol_id", sa.Integer(),
            sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("input_digest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("patrol_id", name="uq_report_patrol"),
    )
    op.create_index("ix_patrol_reports_patrol_id", "patrol_reports", ["patrol_id"])


def downgrade() -> None:
    op.drop_index("ix_patrol_reports_patrol_id", table_name="patrol_reports")
    op.drop_table("patrol_reports")
