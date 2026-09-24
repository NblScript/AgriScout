"""软件闭环：风险预测、随访、复巡任务、数据集和模型评估。

Revision ID: 0009
Revises: 0008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patrol_id", sa.Integer(), sa.ForeignKey("patrols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_point_id", sa.Integer(), sa.ForeignKey("capture_points.id", ondelete="SET NULL")),
        sa.Column("observation_key", sa.String(160), nullable=False),
        sa.Column("target_event", sa.String(120), nullable=False),
        sa.Column("forecast_hours", sa.Integer(), nullable=False),
        sa.Column("forecast_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("trend", sa.String(20), nullable=False, server_default="stable"),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "patrol_id", "capture_point_id", "target_event", "forecast_start",
            "forecast_hours", "model_version", name="uq_risk_prediction_window",
        ),
    )
    op.create_index("ix_risk_predictions_patrol_id", "risk_predictions", ["patrol_id"])
    op.create_index("ix_risk_predictions_observation_key", "risk_predictions", ["observation_key"])
    op.create_table(
        "risk_follow_ups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("risk_prediction_id", sa.Integer(), sa.ForeignKey("risk_predictions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(80)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("event_confirmed", sa.Boolean()),
        sa.Column("event_at", sa.DateTime(timezone=True)),
        sa.Column("intervention_at", sa.DateTime(timezone=True)),
        sa.Column("evidence", sa.JSON()),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_risk_follow_ups_risk_prediction_id", "risk_follow_ups", ["risk_prediction_id"])
    op.create_table(
        "revisit_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patrol_id", sa.Integer(), sa.ForeignKey("patrols.id", ondelete="SET NULL")),
        sa.Column("capture_point_id", sa.Integer(), sa.ForeignKey("capture_points.id", ondelete="SET NULL")),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL")),
        sa.Column("risk_prediction_id", sa.Integer(), sa.ForeignKey("risk_predictions.id", ondelete="SET NULL")),
        sa.Column("task_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("value_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(80), nullable=False, server_default="system"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("risk_prediction_id", name="uq_revisit_task_prediction"),
    )
    for column in ("field_id", "patrol_id", "capture_point_id", "device_id", "risk_prediction_id"):
        op.create_index(f"ix_revisit_tasks_{column}", "revisit_tasks", [column])
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("source_filter", sa.JSON(), nullable=False),
        sa.Column("label_schema", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(80), nullable=False, server_default="system"),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_dataset_name_version"),
    )
    op.create_table(
        "model_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), sa.ForeignKey("dataset_versions.id", ondelete="SET NULL")),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("split", sa.String(20), nullable=False, server_default="test"),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("notes", sa.Text()),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(80)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_evaluations_dataset_version_id", "model_evaluations", ["dataset_version_id"])


def downgrade() -> None:
    op.drop_index("ix_model_evaluations_dataset_version_id", table_name="model_evaluations")
    op.drop_table("model_evaluations")
    op.drop_table("dataset_versions")
    for column in ("risk_prediction_id", "device_id", "capture_point_id", "patrol_id", "field_id"):
        op.drop_index(f"ix_revisit_tasks_{column}", table_name="revisit_tasks")
    op.drop_table("revisit_tasks")
    op.drop_index("ix_risk_follow_ups_risk_prediction_id", table_name="risk_follow_ups")
    op.drop_table("risk_follow_ups")
    op.drop_index("ix_risk_predictions_observation_key", table_name="risk_predictions")
    op.drop_index("ix_risk_predictions_patrol_id", table_name="risk_predictions")
    op.drop_table("risk_predictions")
