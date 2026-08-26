"""M2 数据接入：patrols / capture_points / weather_samples 三表

Revision ID: 0002
Revises: 0001
Create Date: 2026-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patrols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("fields.id"), nullable=False),
        sa.Column("planting_id", sa.Integer(), sa.ForeignKey("plantings.id"), nullable=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        # GeoJSON LineString 文本（基线 B1）
        sa.Column("track", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("analysis_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patrols_field_id", "patrols", ["field_id"])
    op.create_index("ix_patrols_planting_id", "patrols", ["planting_id"])
    op.create_index("ix_patrols_device_id", "patrols", ["device_id"])

    op.create_table(
        "capture_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "patrol_id", sa.Integer(),
            sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("patrol_id", "seq", name="uq_capture_patrol_seq"),
    )
    op.create_index("ix_capture_points_patrol_id", "capture_points", ["patrol_id"])

    op.create_table(
        "weather_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "capture_point_id", sa.Integer(),
            sa.ForeignKey("capture_points.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "patrol_id", sa.Integer(),
            sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("temp_c", sa.Float(), nullable=True),
        sa.Column("humidity_pct", sa.Float(), nullable=True),
        sa.Column("light_lux", sa.Float(), nullable=True),
        sa.Column("wind_mps", sa.Float(), nullable=True),
        sa.Column("rain_mm", sa.Float(), nullable=True),
        sa.Column("soil_temp_c", sa.Float(), nullable=True),
        sa.Column("soil_moisture_pct", sa.Float(), nullable=True),
        # 唯一约束必须内联在建表语句里：SQLite 不支持事后 ALTER ADD CONSTRAINT
        sa.UniqueConstraint("capture_point_id", name="uq_weather_point"),
    )
    op.create_index("ix_weather_samples_patrol_id", "weather_samples", ["patrol_id"])


def downgrade() -> None:
    op.drop_index("ix_weather_samples_patrol_id", table_name="weather_samples")
    op.drop_table("weather_samples")
    op.drop_index("ix_capture_points_patrol_id", table_name="capture_points")
    op.drop_table("capture_points")
    op.drop_index("ix_patrols_device_id", table_name="patrols")
    op.drop_index("ix_patrols_planting_id", table_name="patrols")
    op.drop_index("ix_patrols_field_id", table_name="patrols")
    op.drop_table("patrols")
