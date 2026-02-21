"""add unique report order id index

Revision ID: 0033_add_unique_report_order_id
Revises: 0032_add_order_consumed_at
Create Date: 2026-02-21 00:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_add_unique_report_order_id"
down_revision = "0032_add_order_consumed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT order_id
            FROM reports
            WHERE order_id IS NOT NULL
            GROUP BY order_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchall()
    if duplicate_rows:
        raise RuntimeError(
            "Duplicate reports.order_id found. Run scripts/db/archive_duplicate_reports_by_order.py before migration."
        )

    op.create_index(
        "ux_reports_order_id_not_null",
        "reports",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL"),
        sqlite_where=sa.text("order_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_reports_order_id_not_null", table_name="reports")
