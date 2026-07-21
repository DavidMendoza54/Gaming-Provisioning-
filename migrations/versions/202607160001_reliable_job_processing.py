"""Add reliable job claiming, retries, and worker heartbeats.

Revision ID: 202607160001
Revises: 202606240001
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "202607160001"
down_revision = "202606240001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("jobs", sa.Column("claimed_by", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE jobs SET status = 'dead' WHERE status = 'failed'")
    op.execute(
        """
        WITH ranked_running_jobs AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY resource_id
                       ORDER BY started_at NULLS LAST, id
                   ) AS position
            FROM jobs
            WHERE status = 'running'
        )
        UPDATE jobs
        SET status = 'queued',
            available_at = now(),
            claimed_by = NULL,
            claimed_at = NULL,
            heartbeat_at = NULL
        WHERE id IN (
            SELECT id FROM ranked_running_jobs WHERE position > 1
        )
        """
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["status", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_resource_status",
        "jobs",
        ["resource_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_jobs_one_running_per_resource",
        "jobs",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "workers",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("current_job_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["current_job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workers_heartbeat_at", "workers", ["heartbeat_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_workers_heartbeat_at", table_name="workers")
    op.drop_table("workers")
    op.drop_index("uq_jobs_one_running_per_resource", table_name="jobs")
    op.drop_index("ix_jobs_resource_status", table_name="jobs")
    op.drop_index("ix_jobs_claimable", table_name="jobs")
    op.drop_column("jobs", "heartbeat_at")
    op.drop_column("jobs", "claimed_at")
    op.drop_column("jobs", "claimed_by")
    op.drop_column("jobs", "available_at")
    op.drop_column("jobs", "max_attempts")
    op.execute("UPDATE jobs SET status = 'failed' WHERE status = 'dead'")
