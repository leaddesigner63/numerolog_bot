"""add order fulfillment fields

Revision ID: 0021_add_order_fulfillment_fields
Revises: 0020_add_user_profile_gender
Create Date: 2026-02-10 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_add_order_fulfillment_fields"
down_revision = "0020_add_user_profile_gender"
branch_labels = None
depends_on = None


order_fulfillment_status_enum = sa.Enum(
    "pending",
    "completed",
    name="orderfulfillmentstatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    order_fulfillment_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "orders",
        sa.Column(
            "fulfillment_status",
            order_fulfillment_status_enum,
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("orders", sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("fulfilled_report_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_orders_fulfillment_status"), "orders", ["fulfillment_status"], unique=False)
    op.create_index(op.f("ix_orders_fulfilled_report_id"), "orders", ["fulfilled_report_id"], unique=False)
    op.create_foreign_key(
        "fk_orders_fulfilled_report_id_reports",
        "orders",
        "reports",
        ["fulfilled_report_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE orders
        SET
            fulfillment_status = 'completed',
            fulfilled_at = (
                SELECT MIN(reports.created_at)
                FROM reports
                WHERE reports.order_id = orders.id
            ),
            fulfilled_report_id = (
                SELECT reports.id
                FROM reports
                WHERE reports.order_id = orders.id
                ORDER BY reports.created_at ASC, reports.id ASC
                LIMIT 1
            )
        WHERE EXISTS (
            SELECT 1
            FROM reports
            WHERE reports.order_id = orders.id
        )
        """
    )

    op.alter_column("orders", "fulfillment_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_orders_fulfilled_report_id_reports", "orders", type_="foreignkey")
    op.drop_index(op.f("ix_orders_fulfilled_report_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_fulfillment_status"), table_name="orders")
    op.drop_column("orders", "fulfilled_report_id")
    op.drop_column("orders", "fulfilled_at")
    op.drop_column("orders", "fulfillment_status")

    bind = op.get_bind()
    order_fulfillment_status_enum.drop(bind, checkfirst=True)
