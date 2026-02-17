"""add marketing consent fields to user profile

Revision ID: 0026_add_user_profile_marketing_consent
Revises: 0025_add_user_profile_personal_data_consent
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_add_user_profile_marketing_consent"
down_revision = "0025_add_user_profile_personal_data_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("marketing_consent_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("marketing_consent_document_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("marketing_consent_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("marketing_consent_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("marketing_consent_revoked_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "marketing_consent_revoked_source")
    op.drop_column("user_profile", "marketing_consent_revoked_at")
    op.drop_column("user_profile", "marketing_consent_source")
    op.drop_column("user_profile", "marketing_consent_document_version")
    op.drop_column("user_profile", "marketing_consent_accepted_at")
