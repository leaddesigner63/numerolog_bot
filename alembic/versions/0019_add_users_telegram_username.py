"""add users telegram username

Revision ID: 0019_add_users_telegram_username
Revises: 0018_add_screen_transition_events
Create Date: 2026-02-08 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0019_add_users_telegram_username"
down_revision = "0018_add_screen_transition_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_username", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "telegram_username")
