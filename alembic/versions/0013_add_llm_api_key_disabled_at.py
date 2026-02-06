"""add disabled_at for llm api keys

Revision ID: 0013_add_llm_api_key_disabled_at
Revises: 0012_add_llm_api_keys
Create Date: 2025-09-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_add_llm_api_key_disabled_at"
down_revision = "0012_add_llm_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_api_keys", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("llm_api_keys", "disabled_at")
