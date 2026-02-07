"""add report jobs

Revision ID: 0014_add_report_jobs
Revises: 0013_add_llm_api_key_disabled_at
Create Date: 2025-09-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_add_report_jobs"
down_revision = "0013_add_llm_api_key_disabled_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    report_job_status_enum = postgresql.ENUM(
        "pending",
        "in_progress",
        "failed",
        "completed",
        name="reportjobstatus",
        create_type=False,
    )
    report_job_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "report_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column(
            "tariff",
            postgresql.ENUM(
                "T0",
                "T1",
                "T2",
                "T3",
                name="tariff",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("status", report_job_status_enum, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("lock_token", sa.String(length=64), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_jobs_user_id", "report_jobs", ["user_id"], unique=False)
    op.create_index("ix_report_jobs_order_id", "report_jobs", ["order_id"], unique=False)
    op.create_index("ix_report_jobs_status", "report_jobs", ["status"], unique=False)
    op.create_index("ix_report_jobs_tariff", "report_jobs", ["tariff"], unique=False)
    op.create_index(
        "ix_report_jobs_lock_token", "report_jobs", ["lock_token"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_report_jobs_lock_token", table_name="report_jobs")
    op.drop_index("ix_report_jobs_tariff", table_name="report_jobs")
    op.drop_index("ix_report_jobs_status", table_name="report_jobs")
    op.drop_index("ix_report_jobs_order_id", table_name="report_jobs")
    op.drop_index("ix_report_jobs_user_id", table_name="report_jobs")
    op.drop_table("report_jobs")
    report_job_status_enum = postgresql.ENUM(
        "pending",
        "in_progress",
        "failed",
        "completed",
        name="reportjobstatus",
        create_type=False,
    )
    report_job_status_enum.drop(op.get_bind(), checkfirst=True)
