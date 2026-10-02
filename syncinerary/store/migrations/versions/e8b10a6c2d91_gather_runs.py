"""Persist gather runs and add explicit preparation states.

Revision ID: e8b10a6c2d91
Revises: d3f81a5c2b74
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e8b10a6c2d91"
down_revision = "d3f81a5c2b74"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE trip_status ADD VALUE IF NOT EXISTS 'draft'")
    op.execute("ALTER TYPE trip_status ADD VALUE IF NOT EXISTS 'gathering'")
    op.create_table("gather_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trip.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("city", sa.Text()),
        sa.Column("completed_units", sa.Integer(), nullable=False),
        sa.Column("total_units", sa.Integer()),
        sa.Column("deck_size", sa.Integer()),
        sa.Column("error_code", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="status_values"),
    )
    op.create_index("uq_gather_run_active_trip", "gather_run", ["trip_id"], unique=True,
                    postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index("ix_gather_run_trip_created", "gather_run", ["trip_id", "created_at"])
    op.create_index("ix_gather_run_pending", "gather_run", ["updated_at"],
                    postgresql_where=sa.text("status IN ('queued', 'running')"))


def downgrade():
    op.drop_table("gather_run")
    # Preserve trips when returning to a version without preparation states.
    op.execute("UPDATE trip SET status = 'setup' WHERE status::text IN ('draft', 'gathering')")
    op.execute("ALTER TABLE trip ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE trip_status RENAME TO trip_status_with_gather")
    op.execute("CREATE TYPE trip_status AS ENUM ('setup','swiping','shortlisting','scheduling','active','disrupted')")
    op.execute("ALTER TABLE trip ALTER COLUMN status TYPE trip_status USING status::text::trip_status")
    op.execute("ALTER TABLE trip ALTER COLUMN status SET DEFAULT 'setup'::trip_status")
    op.execute("DROP TYPE trip_status_with_gather")
