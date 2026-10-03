"""棚内环境读数表 + 复巡任务挂株（计划 0015）。

Revision ID: 0016
Revises: 0015
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "env_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sensor_key", sa.String(length=40), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temp_c", sa.Float(), nullable=False),
        sa.Column("humidity_pct", sa.Float(), nullable=False),
        sa.Column("leaf_wetness", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="sensor"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("field_id", "sensor_key", "observed_at", name="uq_env_reading_sensor_time"),
    )
    op.create_index("ix_env_readings_field_time", "env_readings", ["field_id", "observed_at"])

    # SQLite 加外键需要重建表：走 batch 模式（PostgreSQL 下等价于普通 ALTER）
    with op.batch_alter_table("revisit_tasks", recreate="always") as batch:
        batch.add_column(sa.Column("observation_unit_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_revisit_tasks_observation_unit_id", "observation_units",
            ["observation_unit_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_revisit_tasks_observation_unit_id", ["observation_unit_id"])


def downgrade() -> None:
    with op.batch_alter_table("revisit_tasks", recreate="always") as batch:
        batch.drop_index("ix_revisit_tasks_observation_unit_id")
        batch.drop_constraint("fk_revisit_tasks_observation_unit_id", type_="foreignkey")
        batch.drop_column("observation_unit_id")

    op.drop_index("ix_env_readings_field_time", table_name="env_readings")
    op.drop_table("env_readings")
