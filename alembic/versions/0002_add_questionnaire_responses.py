"""add questionnaire responses

Revision ID: 0002_add_questionnaire_responses
Revises: 0001_create_core_tables
Create Date: 2024-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_add_questionnaire_responses"
down_revision = "0001_create_core_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    questionnaire_status = postgresql.ENUM(
        "in_progress",
        "completed",
        name="questionnairestatus",
        create_type=False,
    )
    questionnaire_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "questionnaire_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("questionnaire_version", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            questionnaire_status,
            nullable=False,
        ),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("current_question_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_questionnaire_responses_questionnaire_version"),
        "questionnaire_responses",
        ["questionnaire_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_questionnaire_responses_status"),
        "questionnaire_responses",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_questionnaire_responses_user_id"),
        "questionnaire_responses",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_questionnaire_responses_user_id"),
        table_name="questionnaire_responses",
    )
    op.drop_index(
        op.f("ix_questionnaire_responses_status"),
        table_name="questionnaire_responses",
    )
    op.drop_index(
        op.f("ix_questionnaire_responses_questionnaire_version"),
        table_name="questionnaire_responses",
    )
    op.drop_table("questionnaire_responses")
    op.execute("DROP TYPE IF EXISTS questionnairestatus")
