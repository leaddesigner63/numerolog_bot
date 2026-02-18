"""add user first touch attribution

Revision ID: 0029_add_user_first_touch_attribution
Revises: 0028_expand_screen_state_screen_id
Create Date: 2026-02-18 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_add_user_first_touch_attribution"
down_revision = "0028_expand_screen_state_screen_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_first_touch_attribution",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("start_payload", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("campaign", sa.Text(), nullable=True),
        sa.Column("placement", sa.Text(), nullable=True),
        sa.Column("raw_parts", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["telegram_user_id"], ["users.telegram_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_first_touch_attribution_telegram_user_id",
        "user_first_touch_attribution",
        ["telegram_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_user_first_touch_attribution_captured_at",
        "user_first_touch_attribution",
        ["captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_first_touch_attribution_captured_at",
        table_name="user_first_touch_attribution",
    )
    op.drop_index(
        "ix_user_first_touch_attribution_telegram_user_id",
        table_name="user_first_touch_attribution",
    )
    op.drop_table("user_first_touch_attribution")
