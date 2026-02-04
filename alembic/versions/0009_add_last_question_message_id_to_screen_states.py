"""add last question message id to screen states

Revision ID: 0009_add_last_question_message_id_to_screen_states
Revises: 0008_add_user_message_ids_to_screen_states
Create Date: 2026-02-03 00:00:02.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_add_last_question_message_id_to_screen_states"
down_revision = "0008_add_user_message_ids_to_screen_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "screen_states", sa.Column("last_question_message_id", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("screen_states", "last_question_message_id")
