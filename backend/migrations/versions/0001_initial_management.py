"""M1 基础管理：fields / crops / devices / plantings 四表

Revision ID: 0001
Revises:
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        # GeoJSON Polygon 文本（基线 B1：浮点+GeoJSON，不用 PostGIS）
        sa.Column("boundary", sa.JSON(), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=True),
        sa.Column("soil_type", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "crops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("variety", sa.String(length=100), nullable=True),
        sa.Column("lifecycle_days", sa.Integer(), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("default_rules", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "plantings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("crop_id", sa.Integer(), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("sowing_date", sa.Date(), nullable=False),
        sa.Column("expected_harvest_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_plantings_field_id", "plantings", ["field_id"])
    op.create_index("ix_plantings_crop_id", "plantings", ["crop_id"])


def downgrade() -> None:
    op.drop_index("ix_plantings_crop_id", table_name="plantings")
    op.drop_index("ix_plantings_field_id", table_name="plantings")
    op.drop_table("plantings")
    op.drop_table("devices")
    op.drop_table("crops")
    op.drop_table("fields")
