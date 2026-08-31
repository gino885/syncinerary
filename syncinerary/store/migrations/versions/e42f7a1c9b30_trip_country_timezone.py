"""Trips carry their country, resolved cities, and timezone.

Cities are typed now, so the trip has to record which country they were
resolved in, where each one actually is, and which clock the days are planned
against. The timezone used to be the constant Asia/Tokyo.

Revision ID: e42f7a1c9b30
Revises: c81b3d5a92f7
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e42f7a1c9b30"
down_revision = "c81b3d5a92f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trip", sa.Column("country", sa.Text(), nullable=True))
    op.add_column(
        "trip",
        sa.Column(
            "resolved_cities",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("trip", sa.Column("timezone", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("trip", "timezone")
    op.drop_column("trip", "resolved_cities")
    op.drop_column("trip", "country")
