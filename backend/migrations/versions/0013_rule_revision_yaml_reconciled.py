"""规则修订案记录 YAML 回写对齐时间（审批结果回写 YAML 后恢复正常同步）。

Revision ID: 0013
Revises: 0012
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rule_revisions",
        sa.Column("yaml_reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("rule_revisions") as batch:
        batch.drop_column("yaml_reconciled_at")
