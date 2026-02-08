"""add feedback archived_at

Revision ID: 0015_add_feedback_archived_at
Revises: 0014_add_report_jobs
Create Date: 2026-02-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0015_add_feedback_archived_at"
down_revision = "0014_add_report_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback_messages",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_feedback_messages_archived_at",
        "feedback_messages",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_messages_archived_at", table_name="feedback_messages")
    op.drop_column("feedback_messages", "archived_at")
