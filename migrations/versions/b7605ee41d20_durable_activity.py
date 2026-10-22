"""durable user activity snapshots

Revision ID: b7605ee41d20
Revises: a14c9d3f5602
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7605ee41d20"
down_revision = "a14c9d3f5602"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_activity_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.String(250), nullable=False),
        sa.Column("activity_type", sa.String(30), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_run_activity_run_sequence", "run_activity_snapshots", ["run_id", "sequence"]
    )
    op.create_index("ix_run_activity_snapshots_run_id", "run_activity_snapshots", ["run_id"])


def downgrade():
    op.drop_table("run_activity_snapshots")
