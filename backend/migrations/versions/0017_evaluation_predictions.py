"""模型评估存逐条预测与平台重算指标（计划 0007 P1-7，决策 D24）。

Revision ID: 0017
Revises: 0016
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_evaluations", sa.Column("predictions", sa.JSON(), nullable=True))
    op.add_column("model_evaluations", sa.Column("platform_metrics", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_evaluations", "platform_metrics")
    op.drop_column("model_evaluations", "predictions")
