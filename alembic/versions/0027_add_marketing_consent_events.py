"""add marketing consent events table

Revision ID: 0027_add_marketing_consent_events
Revises: 0026_add_user_profile_marketing_consent
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_add_marketing_consent_events"
down_revision = "0026_add_user_profile_marketing_consent"
branch_labels = None
depends_on = None


marketing_consent_event_type_enum = sa.Enum(
    "accepted",
    "revoked",
    name="marketingconsenteventtype",
)


def upgrade() -> None:
    marketing_consent_event_type_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "marketing_consent_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", marketing_consent_event_type_enum, nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_version", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_marketing_consent_events_user_id",
        "marketing_consent_events",
        ["user_id"],
    )
    op.create_index(
        "ix_marketing_consent_events_event_type",
        "marketing_consent_events",
        ["event_type"],
    )
    op.create_index(
        "ix_marketing_consent_events_event_at",
        "marketing_consent_events",
        ["event_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_marketing_consent_events_event_at", table_name="marketing_consent_events")
    op.drop_index("ix_marketing_consent_events_event_type", table_name="marketing_consent_events")
    op.drop_index("ix_marketing_consent_events_user_id", table_name="marketing_consent_events")
    op.drop_table("marketing_consent_events")
    marketing_consent_event_type_enum.drop(op.get_bind(), checkfirst=True)
