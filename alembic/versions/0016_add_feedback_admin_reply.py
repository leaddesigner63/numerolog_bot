"""add feedback admin reply fields

Revision ID: 0016_add_feedback_admin_reply
Revises: 0015_add_feedback_archived_at
Create Date: 2026-02-08 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016_add_feedback_admin_reply"
down_revision = "0015_add_feedback_archived_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback_messages", sa.Column("admin_reply", sa.Text(), nullable=True))
    op.add_column("feedback_messages", sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback_messages", "replied_at")
    op.drop_column("feedback_messages", "admin_reply")
