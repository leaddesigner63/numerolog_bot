"""add order payment confirmation fields

Revision ID: 0022_add_order_payment_confirmation_fields
Revises: 0021_add_order_fulfillment_fields
Create Date: 2026-02-13 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_add_order_payment_confirmation_fields"
down_revision = "0021_add_order_fulfillment_fields"
branch_labels = None
depends_on = None


payment_confirmation_source_enum = sa.Enum(
    "provider_webhook",
    "provider_poll",
    "admin_manual",
    "system",
    name="paymentconfirmationsource",
)


def upgrade() -> None:
    bind = op.get_bind()
    payment_confirmation_source_enum.create(bind, checkfirst=True)

    op.add_column("orders", sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "orders",
        sa.Column("payment_confirmation_source", payment_confirmation_source_enum, nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_index(
        op.f("ix_orders_payment_confirmed_at"),
        "orders",
        ["payment_confirmed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_orders_payment_confirmation_source"),
        "orders",
        ["payment_confirmation_source"],
        unique=False,
    )

    op.alter_column("orders", "payment_confirmed", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_payment_confirmation_source"), table_name="orders")
    op.drop_index(op.f("ix_orders_payment_confirmed_at"), table_name="orders")

    op.drop_column("orders", "payment_confirmed")
    op.drop_column("orders", "payment_confirmation_source")
    op.drop_column("orders", "payment_confirmed_at")

    bind = op.get_bind()
    payment_confirmation_source_enum.drop(bind, checkfirst=True)
