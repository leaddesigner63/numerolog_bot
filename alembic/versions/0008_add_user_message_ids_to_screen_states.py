"""add user message ids to screen states

Revision ID: 0008_add_user_message_ids_to_screen_states
Revises: 0007_merge_profile_text_fields_heads
Create Date: 2026-02-03 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_add_user_message_ids_to_screen_states"
down_revision = "0007_merge_profile_text_fields_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("screen_states", sa.Column("user_message_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("screen_states", "user_message_ids")
