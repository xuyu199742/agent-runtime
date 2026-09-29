"""rename model call limit and track checkpoint retention

Revision ID: 8e2d64a93b17
Revises: 47d8b2960e11
"""

import sqlalchemy as sa
from alembic import op

revision = "8e2d64a93b17"
down_revision = "47d8b2960e11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agents", "max_steps", new_column_name="max_model_calls")
    op.add_column("runs", sa.Column("checkpoint_pruned_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE runs SET status = 'RUNNING', lease_until = now() - interval '1 second' "
        "WHERE status = 'INTERRUPTED'"
    )


def downgrade() -> None:
    op.drop_column("runs", "checkpoint_pruned_at")
    op.alter_column("agents", "max_model_calls", new_column_name="max_steps")
