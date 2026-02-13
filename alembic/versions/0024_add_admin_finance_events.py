"""add admin finance events

Revision ID: 0024_add_admin_finance_events
Revises: 0023_backfill_order_payment_confirmation
Create Date: 2026-02-13 00:00:03.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_add_admin_finance_events"
down_revision = "0023_backfill_order_payment_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_finance_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("payload_before", sa.JSON(), nullable=True),
        sa.Column("payload_after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_finance_events_order_id", "admin_finance_events", ["order_id"])
    op.create_index("ix_admin_finance_events_action", "admin_finance_events", ["action"])
    op.create_index("ix_admin_finance_events_actor", "admin_finance_events", ["actor"])
    op.create_index("ix_admin_finance_events_created_at", "admin_finance_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_finance_events_created_at", table_name="admin_finance_events")
    op.drop_index("ix_admin_finance_events_actor", table_name="admin_finance_events")
    op.drop_index("ix_admin_finance_events_action", table_name="admin_finance_events")
    op.drop_index("ix_admin_finance_events_order_id", table_name="admin_finance_events")
    op.drop_table("admin_finance_events")
