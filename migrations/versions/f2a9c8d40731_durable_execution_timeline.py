"""durable execution timeline and model executions

Revision ID: f2a9c8d40731
Revises: e7b4c2a91d08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a9c8d40731"
down_revision: str | Sequence[str] | None = "e7b4c2a91d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("trace_sequence", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("run_trace_events", sa.Column("sequence", sa.Integer(), nullable=True))
    op.add_column(
        "run_trace_events", sa.Column("attempt", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("run_trace_events", sa.Column("ref_type", sa.String(length=50)))
    op.add_column("run_trace_events", sa.Column("ref_id", sa.String(length=100)))
    op.execute(
        """
        UPDATE run_trace_events AS event
        SET sequence = numbered.position
        FROM (
            SELECT id, row_number() OVER (PARTITION BY run_id ORDER BY id) AS position
            FROM run_trace_events
        ) AS numbered
        WHERE event.id = numbered.id
        """
    )
    op.execute(
        """
        UPDATE runs AS run
        SET trace_sequence = COALESCE(
            (SELECT MAX(event.sequence) FROM run_trace_events AS event WHERE event.run_id = run.id),
            0
        )
        """
    )
    op.alter_column("run_trace_events", "sequence", nullable=False)
    op.create_unique_constraint(
        "uq_run_trace_run_sequence", "run_trace_events", ["run_id", "sequence"]
    )
    op.create_table(
        "model_executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("step_id", sa.String(length=200), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_messages", postgresql.JSONB(), nullable=False),
        sa.Column("output_message", postgresql.JSONB()),
        sa.Column("tool_calls", postgresql.JSONB()),
        sa.Column("usage", postgresql.JSONB()),
        sa.Column("finish_reason", sa.String(length=60)),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=40)),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "step_id", "attempt", name="uq_model_execution_step_attempt"),
    )
    op.create_index("ix_model_executions_run_id", "model_executions", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_model_executions_run_id", table_name="model_executions")
    op.drop_table("model_executions")
    op.drop_constraint("uq_run_trace_run_sequence", "run_trace_events", type_="unique")
    op.drop_column("run_trace_events", "ref_id")
    op.drop_column("run_trace_events", "ref_type")
    op.drop_column("run_trace_events", "attempt")
    op.drop_column("run_trace_events", "sequence")
    op.drop_column("runs", "trace_sequence")
