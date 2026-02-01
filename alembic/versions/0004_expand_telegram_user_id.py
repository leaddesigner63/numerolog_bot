"""expand telegram user id columns

Revision ID: 0004_expand_telegram_user_id
Revises: 0003_add_screen_states
Create Date: 2026-02-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_expand_telegram_user_id"
down_revision = "0003_add_screen_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "telegram_user_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "screen_states",
        "telegram_user_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "screen_states",
        "telegram_user_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "telegram_user_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
