"""add screen transition events

Revision ID: 0018_add_screen_transition_events
Revises: 0017_add_support_dialog_history
Create Date: 2026-02-08 01:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0018_add_screen_transition_events"
down_revision = "0017_add_support_dialog_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    trigger_type_enum = postgresql.ENUM(
        "callback",
        "message",
        "system",
        "job",
        "admin",
        "unknown",
        name="screentransitiontriggertype",
        create_type=False,
    )
    transition_status_enum = postgresql.ENUM(
        "success",
        "blocked",
        "error",
        "unknown",
        name="screentransitionstatus",
        create_type=False,
    )
    bind = op.get_bind()
    trigger_type_enum.create(bind, checkfirst=True)
    transition_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "screen_transition_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("from_screen_id", sa.String(length=32), nullable=True),
        sa.Column("to_screen_id", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("trigger_type", trigger_type_enum, nullable=False, server_default="unknown"),
        sa.Column("trigger_value", sa.String(length=128), nullable=False, server_default="unknown"),
        sa.Column("transition_status", transition_status_enum, nullable=False, server_default="unknown"),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=True,
            server_default=sa.text(
                "'{\"tariff\": null, \"report_job_status\": null, \"provider\": null, \"reason\": null}'::json"
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_screen_transition_events_telegram_user_id",
        "screen_transition_events",
        ["telegram_user_id"],
    )
    op.create_index(
        "ix_screen_transition_events_from_screen_id",
        "screen_transition_events",
        ["from_screen_id"],
    )
    op.create_index(
        "ix_screen_transition_events_to_screen_id",
        "screen_transition_events",
        ["to_screen_id"],
    )
    op.create_index(
        "ix_screen_transition_events_created_at",
        "screen_transition_events",
        ["created_at"],
    )
    op.create_index(
        "ix_screen_transition_events_to_screen_id_created_at",
        "screen_transition_events",
        ["to_screen_id", "created_at"],
    )
    op.create_index(
        "ix_screen_transition_events_from_to_created_at",
        "screen_transition_events",
        ["from_screen_id", "to_screen_id", "created_at"],
    )
    op.create_index(
        "ix_screen_transition_events_tg_user_created_at",
        "screen_transition_events",
        ["telegram_user_id", "created_at"],
    )

    op.alter_column("screen_transition_events", "telegram_user_id", server_default=None)
    op.alter_column("screen_transition_events", "to_screen_id", server_default=None)
    op.alter_column("screen_transition_events", "trigger_type", server_default=None)
    op.alter_column("screen_transition_events", "trigger_value", server_default=None)
    op.alter_column("screen_transition_events", "transition_status", server_default=None)
    op.alter_column("screen_transition_events", "metadata", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_screen_transition_events_tg_user_created_at", table_name="screen_transition_events")
    op.drop_index("ix_screen_transition_events_from_to_created_at", table_name="screen_transition_events")
    op.drop_index("ix_screen_transition_events_to_screen_id_created_at", table_name="screen_transition_events")
    op.drop_index("ix_screen_transition_events_created_at", table_name="screen_transition_events")
    op.drop_index("ix_screen_transition_events_to_screen_id", table_name="screen_transition_events")
    op.drop_index("ix_screen_transition_events_from_screen_id", table_name="screen_transition_events")
    op.drop_index("ix_screen_transition_events_telegram_user_id", table_name="screen_transition_events")
    op.drop_table("screen_transition_events")

    transition_status_enum = postgresql.ENUM(
        "success",
        "blocked",
        "error",
        "unknown",
        name="screentransitionstatus",
        create_type=False,
    )
    trigger_type_enum = postgresql.ENUM(
        "callback",
        "message",
        "system",
        "job",
        "admin",
        "unknown",
        name="screentransitiontriggertype",
        create_type=False,
    )
    bind = op.get_bind()
    transition_status_enum.drop(bind, checkfirst=True)
    trigger_type_enum.drop(bind, checkfirst=True)
