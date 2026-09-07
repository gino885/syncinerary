"""M7g: a replan trigger for a revision the traveler asked for.

Guided redo reuses the rescue path rather than adding a second way to build an
itinerary version, so it needs a trigger of its own. Overloading `other` would
have worked and would have made every trace ambiguous about whether a person
or a disruption caused the change, which is the one thing the HITL gate exists
to keep straight.

Revision ID: a7d2e4b91c05
Revises: f5a91c3d7e08
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7d2e4b91c05"
down_revision: str | Sequence[str] | None = "f5a91c3d7e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on older servers, and
    # IF NOT EXISTS keeps a re-run harmless.
    op.execute("ALTER TYPE replan_trigger ADD VALUE IF NOT EXISTS 'user_request'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type. Removing it would mean
    # rewriting the type and every column using it, which is not worth doing
    # to undo an additive change: rows already written with it would have no
    # valid value to fall back to.
    pass
