"""store encrypted model credential in database

Revision ID: 47d8b2960e11
Revises: cbf444d5ad1e
"""

import sqlalchemy as sa
from alembic import op

revision = "47d8b2960e11"
down_revision = "cbf444d5ad1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_configs", sa.Column("api_key_encrypted", sa.Text(), nullable=True))
    op.drop_column("model_configs", "api_key_env")


def downgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column(
            "api_key_env", sa.String(length=100), nullable=False, server_default="OPENAI_API_KEY"
        ),
    )
    op.drop_column("model_configs", "api_key_encrypted")
