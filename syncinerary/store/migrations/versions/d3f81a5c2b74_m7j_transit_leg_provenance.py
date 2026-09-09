"""M7j: keep which provider routed each itinerary leg

Transit lookups now walk a chain of providers before falling back to a
distance estimate, and the leg label the app shows deliberately says only
"routed" or "approximate". This column keeps the part that must not be lost
with it: which adapter actually answered. It is read for debugging, for
provider coverage measurement, and for the data-source credits some
providers' licences require.

Nullable with no default: rows written before this migration genuinely do
not know, and inventing a provider for them would be worse than admitting it.

Revision ID: d3f81a5c2b74
Revises: b8e3f5c2a716
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f81a5c2b74"
down_revision: str | Sequence[str] | None = "b8e3f5c2a716"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "itinerary_node",
        sa.Column("transit_from_prev_provider", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("itinerary_node", "transit_from_prev_provider")
