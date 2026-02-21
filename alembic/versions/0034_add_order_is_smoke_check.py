"""add order is_smoke_check flag

Revision ID: 0034_add_order_is_smoke_check
Revises: 0033_add_unique_report_order_id
Create Date: 2026-02-21 01:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0034_add_order_is_smoke_check"
down_revision = "0033_add_unique_report_order_id"
branch_labels = None
depends_on = None


_DEPLOY_SMOKE_ORDER_PROVIDER_PREFIX = "smoke-%"
_DEPLOY_SMOKE_PROFILE_NAME = "Smoke Check"


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("is_smoke_check", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_orders_is_smoke_check", "orders", ["is_smoke_check"], unique=False)

    op.execute(
        sa.text(
            """
            UPDATE orders
            SET is_smoke_check = TRUE
            WHERE provider_payment_id LIKE :smoke_prefix
               OR user_id IN (
                    SELECT user_id
                    FROM user_profile
                    WHERE COALESCE(name, '') = :profile_name
               )
            """
        ).bindparams(
            smoke_prefix=_DEPLOY_SMOKE_ORDER_PROVIDER_PREFIX,
            profile_name=_DEPLOY_SMOKE_PROFILE_NAME,
        )
    )

    op.alter_column("orders", "is_smoke_check", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_orders_is_smoke_check", table_name="orders")
    op.drop_column("orders", "is_smoke_check")
