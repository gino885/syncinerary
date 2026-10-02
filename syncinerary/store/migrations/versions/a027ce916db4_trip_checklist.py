"""Shared editable trip checklist with durable suggestion suppression.

Revision ID: a027ce916db4
Revises: f019a7c35b82
"""
from alembic import op
import sqlalchemy as sa

revision = "a027ce916db4"
down_revision = "f019a7c35b82"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("trip_checklist_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trip.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False, server_default=""),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_key", sa.String(300), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trip_id", "source_key"))


def downgrade():
    op.drop_table("trip_checklist_item")
