"""add admin notes

Revision ID: 0010_add_admin_notes
Revises: 0009_add_last_question_message_id_to_screen_states
Create Date: 2026-02-03 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_add_admin_notes"
down_revision = "0009_add_last_question_message_id_to_screen_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("admin_notes")
