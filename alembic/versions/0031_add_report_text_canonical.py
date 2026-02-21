"""add report canonical text

Revision ID: 0031_add_report_text_canonical
Revises: 0030_add_service_heartbeats
Create Date: 2026-02-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_add_report_text_canonical"
down_revision = "0030_add_service_heartbeats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("report_text_canonical", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "report_text_canonical")
