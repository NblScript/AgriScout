"""M4 建议引擎：rules / advices 两表

Revision ID: 0004
Revises: 0003
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_key", sa.String(length=80), nullable=False, unique=True),
        sa.Column("crop_id", sa.Integer(), sa.ForeignKey("crops.id"), nullable=True),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("condition", sa.JSON(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rules_crop_id", "rules", ["crop_id"])

    op.create_table(
        "advices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "patrol_id", sa.Integer(),
            sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "capture_point_id", sa.Integer(),
            sa.ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id"), nullable=True),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="suggested"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_advices_patrol_id", "advices", ["patrol_id"])
    op.create_index("ix_advices_capture_point_id", "advices", ["capture_point_id"])


def downgrade() -> None:
    op.drop_index("ix_advices_capture_point_id", table_name="advices")
    op.drop_index("ix_advices_patrol_id", table_name="advices")
    op.drop_table("advices")
    op.drop_index("ix_rules_crop_id", table_name="rules")
    op.drop_table("rules")
