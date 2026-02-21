"""add order consumed_at marker

Revision ID: 0032_add_order_consumed_at
Revises: 0031_add_report_text_canonical
Create Date: 2026-02-21 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_add_order_consumed_at"
down_revision = "0031_add_report_text_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_orders_consumed_at"), "orders", ["consumed_at"], unique=False)

    op.execute(
        """
        UPDATE orders
        SET consumed_at = COALESCE(fulfilled_at, paid_at, created_at, CURRENT_TIMESTAMP)
        WHERE status = 'paid'
          AND fulfillment_status = 'completed'
          AND consumed_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_consumed_at"), table_name="orders")
    op.drop_column("orders", "consumed_at")
