"""Persist cross-Run external effect identity.

Revision ID: f6d2a4c0e19b
Revises: f2a9c8d40731
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6d2a4c0e19b"
down_revision: str | Sequence[str] | None = "f2a9c8d40731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "effect_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_namespace", sa.String(length=200), nullable=False),
        sa.Column("operation_name", sa.String(length=100), nullable=False),
        sa.Column("business_key", sa.String(length=200), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("origin_run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("dispatch_run_id", sa.String(length=36), sa.ForeignKey("runs.id")),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("reconcile_run_id", sa.String(length=36), sa.ForeignKey("runs.id")),
        sa.Column("reconcile_worker_id", sa.String(length=100)),
        sa.Column("external_ref", sa.String(length=200)),
        sa.Column("result_content", sa.Text()),
        sa.Column("error_code", sa.String(length=40)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider_namespace", "operation_name", "business_key", name="uq_effect_identity"
        ),
    )
    op.create_index("ix_effect_records_origin_run_id", "effect_records", ["origin_run_id"])
    op.add_column("tool_executions", sa.Column("effect_id", sa.String(length=36)))
    op.create_foreign_key(
        "fk_tool_executions_effect_id", "tool_executions", "effect_records", ["effect_id"], ["id"]
    )
    op.create_index("ix_tool_executions_effect_id", "tool_executions", ["effect_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_executions_effect_id", table_name="tool_executions")
    op.drop_constraint("fk_tool_executions_effect_id", "tool_executions", type_="foreignkey")
    op.drop_column("tool_executions", "effect_id")
    op.drop_index("ix_effect_records_origin_run_id", table_name="effect_records")
    op.drop_table("effect_records")
