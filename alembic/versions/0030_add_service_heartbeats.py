"""add service heartbeats

Revision ID: 0030_add_service_heartbeats
Revises: 0029_add_user_first_touch_attribution
Create Date: 2026-02-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_add_service_heartbeats"
down_revision = "0029_add_user_first_touch_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_heartbeats",
        sa.Column("service_name", sa.String(length=64), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("service_name"),
    )


def downgrade() -> None:
    op.drop_table("service_heartbeats")
