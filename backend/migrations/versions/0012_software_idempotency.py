"""为软件闭环的重试与任务归属补齐数据库保护。"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("revisit_tasks")}
    if "risk_prediction_id" not in task_columns:
        op.add_column(
            "revisit_tasks",
            sa.Column(
                "risk_prediction_id", sa.Integer(),
                sa.ForeignKey("risk_predictions.id", ondelete="SET NULL"), nullable=True,
            ),
        )
    task_indexes = {index["name"] for index in inspector.get_indexes("revisit_tasks")}
    if "ix_revisit_tasks_risk_prediction_id" not in task_indexes:
        op.create_index(
            "ix_revisit_tasks_risk_prediction_id", "revisit_tasks", ["risk_prediction_id"],
        )
    task_unique = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("revisit_tasks")
    }
    if "uq_revisit_task_prediction" not in task_unique:
        with op.batch_alter_table("revisit_tasks", recreate="always") as batch:
            batch.create_unique_constraint("uq_revisit_task_prediction", ["risk_prediction_id"])

    risk_unique = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("risk_predictions")
    }
    if "uq_risk_prediction_window" not in risk_unique:
        # batch mode keeps this valid on SQLite as well as PostgreSQL.
        with op.batch_alter_table("risk_predictions", recreate="always") as batch:
            batch.create_unique_constraint(
                "uq_risk_prediction_window",
                [
                    "patrol_id", "capture_point_id", "target_event", "forecast_start",
                    "forecast_hours", "model_version",
                ],
            )


def downgrade() -> None:
    # 0009 is now authored with these protections. Keeping them on downgrade
    # also makes this compatibility migration safe for databases that already
    # ran the canonical 0009 before 0012 was introduced.
    pass
