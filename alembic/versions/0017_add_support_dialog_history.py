"""add support dialog history

Revision ID: 0017_add_support_dialog_history
Revises: 0016_add_feedback_admin_reply
Create Date: 2026-02-08 00:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0017_add_support_dialog_history"
down_revision = "0016_add_feedback_admin_reply"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback_messages",
        sa.Column("parent_feedback_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_feedback_messages_parent_feedback_id",
        "feedback_messages",
        "feedback_messages",
        ["parent_feedback_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_feedback_messages_parent_feedback_id",
        "feedback_messages",
        ["parent_feedback_id"],
    )

    direction_enum = sa.Enum("user", "admin", name="supportmessagedirection")
    bind = op.get_bind()
    direction_enum.create(bind, checkfirst=True)

    op.create_table(
        "support_dialog_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("thread_feedback_id", sa.Integer(), nullable=False),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_feedback_id"], ["feedback_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_dialog_messages_user_id", "support_dialog_messages", ["user_id"])
    op.create_index(
        "ix_support_dialog_messages_thread_feedback_id",
        "support_dialog_messages",
        ["thread_feedback_id"],
    )
    op.create_index("ix_support_dialog_messages_direction", "support_dialog_messages", ["direction"])
    op.create_index("ix_support_dialog_messages_created_at", "support_dialog_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_support_dialog_messages_created_at", table_name="support_dialog_messages")
    op.drop_index("ix_support_dialog_messages_direction", table_name="support_dialog_messages")
    op.drop_index("ix_support_dialog_messages_thread_feedback_id", table_name="support_dialog_messages")
    op.drop_index("ix_support_dialog_messages_user_id", table_name="support_dialog_messages")
    op.drop_table("support_dialog_messages")

    op.drop_index("ix_feedback_messages_parent_feedback_id", table_name="feedback_messages")
    op.drop_constraint("fk_feedback_messages_parent_feedback_id", "feedback_messages", type_="foreignkey")
    op.drop_column("feedback_messages", "parent_feedback_id")

    direction_enum = sa.Enum("user", "admin", name="supportmessagedirection")
    bind = op.get_bind()
    direction_enum.drop(bind, checkfirst=True)
