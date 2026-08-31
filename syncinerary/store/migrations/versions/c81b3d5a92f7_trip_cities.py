"""Trips carry the list of cities the traveler typed.

A trip used to be one destination string chosen from a fixed list. Travelers
type their own cities now, and more than one, so the searched cities are stored
as their own ordered column rather than being parsed back out of a label.

Revision ID: c81b3d5a92f7
Revises: 43c4a7c6f1e2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "c81b3d5a92f7"
down_revision = "43c4a7c6f1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trip",
        sa.Column(
            "cities",
            ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    # Existing trips were single destination trips, so the destination they
    # already carry is their one city.
    op.execute(
        "UPDATE trip SET cities = ARRAY[destination] "
        "WHERE cities = '{}'::text[] AND destination <> ''"
    )


def downgrade() -> None:
    op.drop_column("trip", "cities")
