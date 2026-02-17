"""add personal data consent fields to user profile

Revision ID: 0025_add_user_profile_personal_data_consent
Revises: 0024_add_admin_finance_events
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_add_user_profile_personal_data_consent"
down_revision = "0024_add_admin_finance_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("personal_data_consent_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("personal_data_consent_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "personal_data_consent_source")
    op.drop_column("user_profile", "personal_data_consent_accepted_at")
