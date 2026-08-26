"""M3 分析管线：analyses 表

Revision ID: 0003
Revises: 0002
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "capture_point_id", sa.Integer(),
            sa.ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False, unique=True,
        ),
        sa.Column(
            "patrol_id", sa.Integer(),
            sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("analyzer_version", sa.String(length=50), nullable=False),
        sa.Column("growth_stage", sa.JSON(), nullable=True),
        sa.Column("vigor_level", sa.Integer(), nullable=True),
        sa.Column("ndvi", sa.Float(), nullable=True),
        sa.Column("disease_detections", sa.JSON(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column(
            "analyzed_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_analyses_patrol_id", "analyses", ["patrol_id"])
    op.create_index(
        "ix_analyses_capture_point_id", "analyses", ["capture_point_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_capture_point_id", table_name="analyses")
    op.drop_index("ix_analyses_patrol_id", table_name="analyses")
    op.drop_table("analyses")
