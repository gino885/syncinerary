"""M7g: the language shared trip content is generated in.

Persisted on the trip rather than read from each request's Accept-Language,
because a trip is collaborative: the narrative and the not-placed reasons are
one artifact the whole group reads, and deriving their language from whichever
traveler happened to trigger the plan would make the stored text depend on
whose phone ran it.

The creator's display language selects this value. It is the language of
content the server writes and stores, and later search code uses its Chinese
versus English choice when composing social queries.

Revision ID: b8e3f5c2a716
Revises: a7d2e4b91c05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e3f5c2a716"
down_revision: str | Sequence[str] | None = "a7d2e4b91c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trip",
        sa.Column(
            "output_locale",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("trip", "output_locale")
