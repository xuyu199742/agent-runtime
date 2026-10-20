"""Add versioned Skills and Agent associations.

Revision ID: a14c9d3f5602
Revises: b7e2a6c4d901
"""

import sqlalchemy as sa
from alembic import op

revision = "a14c9d3f5602"
down_revision = "b7e2a6c4d901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("when_to_use", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "skill_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("skill_id", "revision"),
    )
    op.create_index("ix_skill_revisions_skill_id", "skill_revisions", ["skill_id"])
    op.create_table(
        "agent_skills",
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("skill_id", sa.String(36), sa.ForeignKey("skills.id"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("agent_skills")
    op.drop_index("ix_skill_revisions_skill_id", table_name="skill_revisions")
    op.drop_table("skill_revisions")
    op.drop_table("skills")
