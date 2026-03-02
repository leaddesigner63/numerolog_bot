"""add user touch events

Revision ID: 0035_add_user_touch_events
Revises: 0034_add_order_is_smoke_check
Create Date: 2026-03-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0035_add_user_touch_events"
down_revision = "0034_add_order_is_smoke_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_touch_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("start_payload", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("campaign", sa.Text(), nullable=True),
        sa.Column("placement", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["telegram_user_id"], ["users.telegram_user_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_user_touch_events_telegram_user_id",
        "user_touch_events",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_touch_events_captured_at",
        "user_touch_events",
        ["captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_touch_events_captured_at", table_name="user_touch_events")
    op.drop_index("ix_user_touch_events_telegram_user_id", table_name="user_touch_events")
    op.drop_table("user_touch_events")
