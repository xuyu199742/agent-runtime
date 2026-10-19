"""Add Agent execution budget defaults.

Revision ID: b7e2a6c4d901
Revises: e4a1b6c9d2f0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2a6c4d901"
down_revision: str | Sequence[str] | None = "e4a1b6c9d2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents", sa.Column("max_tool_calls", sa.Integer(), nullable=False, server_default="30")
    )
    op.add_column(
        "agents", sa.Column("max_external_writes", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "agents", sa.Column("max_duration_seconds", sa.Integer(), nullable=False, server_default="3600")
    )


def downgrade() -> None:
    op.drop_column("agents", "max_duration_seconds")
    op.drop_column("agents", "max_external_writes")
    op.drop_column("agents", "max_tool_calls")
