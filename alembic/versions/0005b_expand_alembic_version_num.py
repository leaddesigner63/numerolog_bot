"""expand alembic version_num length

Revision ID: 0005b_expand_alembic_version_num
Revises: 0005_change_birth_date_format
Create Date: 2026-02-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005b_expand_alembic_version_num"
down_revision = "0005_change_birth_date_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        nullable=False,
    )
