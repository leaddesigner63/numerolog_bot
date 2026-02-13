"""backfill order payment confirmation

Revision ID: 0023_backfill_order_payment_confirmation
Revises: 0022_add_order_payment_confirmation_fields
Create Date: 2026-02-13 00:00:02.000000
"""

from alembic import op


revision = "0023_backfill_order_payment_confirmation"
down_revision = "0022_add_order_payment_confirmation_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE orders
        SET
            payment_confirmed = TRUE,
            payment_confirmed_at = COALESCE(payment_confirmed_at, paid_at),
            payment_confirmation_source = COALESCE(payment_confirmation_source, 'system')
        WHERE
            status = 'paid'
            AND provider_payment_id IS NOT NULL
            AND TRIM(provider_payment_id) <> ''
            AND COALESCE(payment_confirmed, FALSE) = FALSE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE orders
        SET
            payment_confirmed = FALSE,
            payment_confirmed_at = NULL,
            payment_confirmation_source = NULL
        WHERE payment_confirmation_source = 'system'
        """
    )
