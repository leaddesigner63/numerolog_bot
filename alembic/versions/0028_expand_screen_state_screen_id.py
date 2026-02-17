"""expand screen_states.screen_id length to 32

Revision ID: 0028_expand_screen_state_screen_id
Revises: 0027_add_marketing_consent_events
Create Date: 2026-02-17 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_expand_screen_state_screen_id"
down_revision = "0027_add_marketing_consent_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "screen_states",
        "screen_id",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "screen_states",
        "screen_id",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=True,
    )
