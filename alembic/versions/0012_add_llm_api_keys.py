"""add llm api keys table

Revision ID: 0012_add_llm_api_keys
Revises: 0011_add_system_prompts
Create Date: 2025-09-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_add_llm_api_keys"
down_revision = "0011_add_system_prompts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.String(length=64), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_llm_api_keys_provider", "llm_api_keys", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_llm_api_keys_provider", table_name="llm_api_keys")
    op.drop_table("llm_api_keys")
