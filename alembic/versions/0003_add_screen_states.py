"""add screen states

Revision ID: 0003_add_screen_states
Revises: 0002_add_questionnaire_responses
Create Date: 2024-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_screen_states"
down_revision = "0002_add_questionnaire_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screen_states",
        sa.Column("telegram_user_id", sa.Integer(), nullable=False),
        sa.Column("screen_id", sa.String(length=16), nullable=True),
        sa.Column("message_ids", sa.JSON(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("telegram_user_id"),
    )


def downgrade() -> None:
    op.drop_table("screen_states")
