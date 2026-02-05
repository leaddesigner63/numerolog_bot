"""add system prompts

Revision ID: 0011_add_system_prompts
Revises: 0010_add_admin_notes
Create Date: 2026-02-03 00:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_add_system_prompts"
down_revision = "0010_add_admin_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_system_prompts_key", "system_prompts", ["key"])


def downgrade() -> None:
    op.drop_index("ix_system_prompts_key", table_name="system_prompts")
    op.drop_table("system_prompts")
