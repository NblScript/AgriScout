"""M6+ 标注回流：annotations 表

Revision ID: 0005
Revises: 0004
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "capture_point_id", sa.Integer(),
            sa.ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "patrol_id", sa.Integer(),
            sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("annotator_name", sa.String(length=80), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("capture_point_id", "label", name="uq_annotation_point_label"),
    )
    op.create_index("ix_annotations_capture_point_id", "annotations", ["capture_point_id"])
    op.create_index("ix_annotations_patrol_id", "annotations", ["patrol_id"])


def downgrade() -> None:
    op.drop_index("ix_annotations_patrol_id", table_name="annotations")
    op.drop_index("ix_annotations_capture_point_id", table_name="annotations")
    op.drop_table("annotations")
