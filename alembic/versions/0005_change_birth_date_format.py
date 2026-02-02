"""change birth date format to string

Revision ID: 0005_change_birth_date_format
Revises: 0004_expand_telegram_user_id
Create Date: 2026-02-01 00:10:00.000000
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "0005_change_birth_date_format"
down_revision = "0004_expand_telegram_user_id"
branch_labels = None
depends_on = None


def _format_birth_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        for pattern in ("%d:%m:%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).strftime("%d:%m:%Y")
            except ValueError:
                continue
        return None
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%d:%m:%Y")
        except Exception:
            return None
    return None


def _parse_birth_date(value: object) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, str):
        for pattern in ("%d:%m:%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                continue
        return None
    if hasattr(value, "date"):
        try:
            return value.date()
        except Exception:
            return None
    return None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("birth_date_text", sa.String(length=10), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT user_id, birth_date FROM user_profile")
    ).fetchall()
    for row in rows:
        formatted = _format_birth_date(row.birth_date)
        if not formatted:
            formatted = "01:01:1970"
        connection.execute(
            sa.text(
                "UPDATE user_profile SET birth_date_text = :birth_date WHERE user_id = :user_id"
            ),
            {"birth_date": formatted, "user_id": row.user_id},
        )
    op.drop_column("user_profile", "birth_date")
    op.alter_column(
        "user_profile",
        "birth_date_text",
        new_column_name="birth_date",
        existing_type=sa.String(length=10),
        nullable=False,
    )


def downgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("birth_date_date", sa.Date(), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT user_id, birth_date FROM user_profile")
    ).fetchall()
    for row in rows:
        parsed = _parse_birth_date(row.birth_date)
        connection.execute(
            sa.text(
                "UPDATE user_profile SET birth_date_date = :birth_date WHERE user_id = :user_id"
            ),
            {"birth_date": parsed, "user_id": row.user_id},
        )
    op.drop_column("user_profile", "birth_date")
    op.alter_column(
        "user_profile",
        "birth_date_date",
        new_column_name="birth_date",
        existing_type=sa.Date(),
        nullable=False,
    )
