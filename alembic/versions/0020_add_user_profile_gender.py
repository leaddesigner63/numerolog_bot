"""add user profile gender

Revision ID: 0020_add_user_profile_gender
Revises: 0019_add_users_telegram_username
Create Date: 2026-02-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0020_add_user_profile_gender"
down_revision = "0019_add_users_telegram_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profile", sa.Column("gender", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profile", "gender")
