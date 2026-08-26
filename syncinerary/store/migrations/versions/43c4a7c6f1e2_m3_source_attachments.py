"""M3 source attachments

Revision ID: 43c4a7c6f1e2
Revises: b270ce1b80cd
Create Date: 2026-08-26 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "43c4a7c6f1e2"
down_revision: Union[str, Sequence[str], None] = "b270ce1b80cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_attachment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("traveler_id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("instagram", "tiktok", "rednote", name="social_platform"),
            nullable=False,
        ),
        sa.Column(
            "input_type",
            sa.Enum("link", "screenshot", name="attachment_input_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "ready",
                "failed",
                name="attachment_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("platform_id", sa.Text(), nullable=True),
        sa.Column("screenshot_storage_key", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_type <> 'link' OR "
            "(original_url IS NOT NULL AND canonical_url IS NOT NULL)",
            name=op.f("ck_source_attachment_link_has_urls"),
        ),
        sa.ForeignKeyConstraint(
            ["traveler_id"],
            ["traveler.id"],
            name=op.f("fk_source_attachment_traveler_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["trip.id"],
            name=op.f("fk_source_attachment_trip_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_attachment")),
        sa.UniqueConstraint(
            "trip_id",
            "traveler_id",
            "canonical_url",
            name="uq_source_attachment_link_per_traveler",
        ),
    )
    op.create_index(
        "ix_source_attachment_trip_id_created_at",
        "source_attachment",
        ["trip_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_attachment_traveler_id"),
        "source_attachment",
        ["traveler_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_attachment_traveler_id"),
        table_name="source_attachment",
    )
    op.drop_index(
        "ix_source_attachment_trip_id_created_at",
        table_name="source_attachment",
    )
    op.drop_table("source_attachment")
    op.execute("DROP TYPE IF EXISTS attachment_status")
    op.execute("DROP TYPE IF EXISTS attachment_input_type")
    op.execute("DROP TYPE IF EXISTS social_platform")
