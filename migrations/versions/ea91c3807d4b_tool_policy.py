"""store tool execution policy

Revision ID: ea91c3807d4b
Revises: 8e2d64a93b17
"""

import sqlalchemy as sa
from alembic import op

revision = "ea91c3807d4b"
down_revision = "8e2d64a93b17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tools", sa.Column("policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
    )
    op.execute(
        "UPDATE tools SET policy = json_build_object('allowed_hosts', config->'allowed_hosts') "
        "WHERE type = 'HTTP' AND config->'allowed_hosts' IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("tools", "policy")
