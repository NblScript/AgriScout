"""数据集冻结快照与模型评估门禁。

Revision ID: 0011
Revises: 0010
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dataset_versions", sa.Column("snapshot_ndjson", sa.Text(), nullable=True))
    op.add_column("dataset_versions", sa.Column("snapshot_sha256", sa.String(length=64), nullable=True))
    op.add_column("dataset_versions", sa.Column("snapshot_summary", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("dataset_versions", "snapshot_summary")
    op.drop_column("dataset_versions", "snapshot_sha256")
    op.drop_column("dataset_versions", "snapshot_ndjson")
