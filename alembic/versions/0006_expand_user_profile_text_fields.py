"""expand user profile text fields

Revision ID: 0006_expand_user_profile_text_fields
Revises: 0005_change_birth_date_format
Create Date: 2026-02-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_expand_user_profile_text_fields"
down_revision = "0005_change_birth_date_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_profile",
        "name",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "user_profile",
        "birth_date",
        existing_type=sa.String(length=10),
        type_=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "user_profile",
        "birth_time",
        existing_type=sa.String(length=5),
        type_=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "user_profile",
        "birth_place_city",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "user_profile",
        "birth_place_region",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "user_profile",
        "birth_place_country",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_profile",
        "birth_place_country",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        nullable=False,
    )
    op.alter_column(
        "user_profile",
        "birth_place_region",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        nullable=True,
    )
    op.alter_column(
        "user_profile",
        "birth_place_city",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        nullable=False,
    )
    op.alter_column(
        "user_profile",
        "birth_time",
        existing_type=sa.Text(),
        type_=sa.String(length=5),
        nullable=True,
    )
    op.alter_column(
        "user_profile",
        "birth_date",
        existing_type=sa.Text(),
        type_=sa.String(length=10),
        nullable=False,
    )
    op.alter_column(
        "user_profile",
        "name",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        nullable=False,
    )
