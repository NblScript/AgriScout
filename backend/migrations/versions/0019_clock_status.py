"""车端时钟状态与时间告警：巡检和心跳各加时钟状态、告警两列，心跳另记时间差（计划 0007 P0-2，决策 D26）。

Revision ID: 0019
Revises: 0018
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("patrols", sa.Column("clock", sa.JSON(), nullable=True))
    op.add_column("patrols", sa.Column("time_warnings", sa.JSON(), nullable=True))
    op.add_column("device_heartbeats", sa.Column("clock", sa.JSON(), nullable=True))
    op.add_column("device_heartbeats", sa.Column("clock_skew_s", sa.Float(), nullable=True))
    op.add_column("device_heartbeats", sa.Column("time_warnings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("device_heartbeats") as batch:
        batch.drop_column("time_warnings")
        batch.drop_column("clock_skew_s")
        batch.drop_column("clock")
    with op.batch_alter_table("patrols") as batch:
        batch.drop_column("time_warnings")
        batch.drop_column("clock")
