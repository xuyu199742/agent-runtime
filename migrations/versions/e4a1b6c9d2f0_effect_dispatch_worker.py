"""Record the Worker that claimed external dispatch.

Revision ID: e4a1b6c9d2f0
Revises: f6d2a4c0e19b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a1b6c9d2f0"
down_revision: str | Sequence[str] | None = "f6d2a4c0e19b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("effect_records", sa.Column("dispatch_worker_id", sa.String(length=100)))


def downgrade() -> None:
    op.drop_column("effect_records", "dispatch_worker_id")
