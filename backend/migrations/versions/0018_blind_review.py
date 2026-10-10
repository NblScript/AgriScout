"""盲法复核：批次、批次里的照片、判读记录（计划 0007 P1-9）。

Revision ID: 0018
Revises: 0017
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "blind_review_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_blind_review_batches_field_id", "blind_review_batches", ["field_id"])

    op.create_table(
        "blind_review_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("blind_review_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_point_id", sa.Integer(), sa.ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("final_label", sa.String(length=50), nullable=True),
        sa.Column("annotation_id", sa.Integer(), sa.ForeignKey("annotations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("batch_id", "capture_point_id", name="uq_blind_item_point"),
        sa.UniqueConstraint("batch_id", "position", name="uq_blind_item_position"),
    )
    for column in ("batch_id", "capture_point_id", "annotation_id"):
        op.create_index(f"ix_blind_review_items_{column}", "blind_review_items", [column])

    op.create_table(
        "blind_review_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("blind_review_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer_name", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("item_id", "reviewer_user_id", name="uq_blind_vote_reviewer"),
    )
    for column in ("item_id", "reviewer_user_id"):
        op.create_index(f"ix_blind_review_votes_{column}", "blind_review_votes", [column])


def downgrade() -> None:
    op.drop_table("blind_review_votes")
    op.drop_table("blind_review_items")
    op.drop_table("blind_review_batches")
