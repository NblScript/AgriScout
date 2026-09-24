"""设备协议：心跳、事件与可回放故障注入。

Revision ID: 0010
Revises: 0009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "device_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_heartbeat_id", sa.String(length=120), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("execution_phase", sa.String(length=40), nullable=False, server_default="idle"),
        sa.Column(
            "mission_id", sa.Integer(), sa.ForeignKey("patrols.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position_source", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("queue_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("battery_pct", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("device_id", "client_heartbeat_id", name="uq_device_heartbeat_client_id"),
    )
    op.create_index("ix_device_heartbeats_device_id", "device_heartbeats", ["device_id"])
    op.create_index("ix_device_heartbeats_client_heartbeat_id", "device_heartbeats", ["client_heartbeat_id"])
    op.create_index("ix_device_heartbeats_mission_id", "device_heartbeats", ["mission_id"])

    op.create_table(
        "device_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "mission_id", sa.Integer(), sa.ForeignKey("patrols.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_event_id", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="device"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_fault_injected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fault_type", sa.String(length=80), nullable=True),
        sa.Column("fault_active", sa.Boolean(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("device_id", "client_event_id", name="uq_device_event_client_id"),
    )
    op.create_index("ix_device_events_device_id", "device_events", ["device_id"])
    op.create_index("ix_device_events_mission_id", "device_events", ["mission_id"])
    op.create_index("ix_device_events_client_event_id", "device_events", ["client_event_id"])


def downgrade() -> None:
    op.drop_index("ix_device_events_client_event_id", table_name="device_events")
    op.drop_index("ix_device_events_mission_id", table_name="device_events")
    op.drop_index("ix_device_events_device_id", table_name="device_events")
    op.drop_table("device_events")
    op.drop_index("ix_device_heartbeats_mission_id", table_name="device_heartbeats")
    op.drop_index("ix_device_heartbeats_client_heartbeat_id", table_name="device_heartbeats")
    op.drop_index("ix_device_heartbeats_device_id", table_name="device_heartbeats")
    op.drop_table("device_heartbeats")\n