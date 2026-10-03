"""株档案表 + 巡检包协议 v2 最小子集列 + 上传幂等（计划 0014）。

Revision ID: 0015
Revises: 0014
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observation_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=True),
        sa.Column("position_no", sa.Integer(), nullable=True),
        sa.Column("chainage_m", sa.Float(), nullable=True),
        sa.Column("tag_code", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_from", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("field_id", "key", name="uq_observation_unit_key"),
        sa.UniqueConstraint("field_id", "tag_code", name="uq_observation_unit_tag"),
    )
    op.create_index("ix_observation_units_field_id", "observation_units", ["field_id"])

    op.add_column("fields", sa.Column("facility_type", sa.String(length=20), nullable=True))

    # SQLite 加外键与唯一约束需要重建表：统一走 batch 模式（PostgreSQL 下等价于普通 ALTER）
    with op.batch_alter_table("patrols", recreate="always") as batch:
        batch.add_column(sa.Column("schema_version", sa.String(length=8), nullable=False, server_default="1.0"))
        batch.add_column(sa.Column("client_package_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("package_sha256", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_patrol_client_package", ["device_id", "client_package_id"])

    with op.batch_alter_table("capture_points", recreate="always") as batch:
        batch.add_column(sa.Column("observation_key", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("observation_unit_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("route_chainage_m", sa.Float(), nullable=True))
        batch.add_column(sa.Column("distance_source", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("position_source", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("view_meta", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_capture_points_observation_unit_id", "observation_units",
            ["observation_unit_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_capture_points_observation_key", ["observation_key"])
        batch.create_index("ix_capture_points_observation_unit_id", ["observation_unit_id"])


def downgrade() -> None:
    with op.batch_alter_table("capture_points", recreate="always") as batch:
        batch.drop_index("ix_capture_points_observation_unit_id")
        batch.drop_index("ix_capture_points_observation_key")
        batch.drop_constraint("fk_capture_points_observation_unit_id", type_="foreignkey")
        for column in ("view_meta", "position_source", "distance_source", "route_chainage_m",
                       "observation_unit_id", "observation_key"):
            batch.drop_column(column)

    with op.batch_alter_table("patrols", recreate="always") as batch:
        batch.drop_constraint("uq_patrol_client_package", type_="unique")
        for column in ("package_sha256", "client_package_id", "schema_version"):
            batch.drop_column(column)

    with op.batch_alter_table("fields") as batch:
        batch.drop_column("facility_type")

    op.drop_index("ix_observation_units_field_id", table_name="observation_units")
    op.drop_table("observation_units")
