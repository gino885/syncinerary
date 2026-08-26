"""M1-1 acceptance: the migrated schema matches CLAUDE.md §7.

These run against the database that `alembic upgrade head` produced, not
against Base.metadata. Asserting the metadata against itself would pass even
if the migration were broken, which is exactly the failure mode worth
catching: the M1 initial revision needed three hand edits that autogenerate
got wrong.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from syncinerary.domain.models import (
    BadgeType,
    CandidateType,
    ConstraintKind,
    ItineraryStatus,
    ReplanStatus,
    ReplanTrigger,
    TripStatus,
    VoteSignal,
)
from syncinerary.store.tables import EMBEDDING_DIM

EXPECTED_TABLES = {
    "agent_run",
    "candidate_badge",
    "candidate_place",
    "eval_result",
    "eval_scenario",
    "itinerary_node",
    "itinerary_version",
    "replan_event",
    "shortlist_state",
    "traveler",
    "trip",
    "trip_constraint",
    "vote",
    "wishlist_not_placed",
}

# Enum type name in Postgres -> the domain enum it must mirror exactly.
EXPECTED_ENUMS = {
    "trip_status": TripStatus,
    "candidate_type": CandidateType,
    "constraint_kind": ConstraintKind,
    "vote_signal": VoteSignal,
    "badge_type": BadgeType,
    "itinerary_status": ItineraryStatus,
    "replan_trigger": ReplanTrigger,
    "replan_status": ReplanStatus,
}


async def test_all_section_7_tables_exist(engine: AsyncEngine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
    actual = {r[0] for r in rows}
    # Only our tables are compared. The LangGraph checkpointer creates its own
    # in this database (see store/migrations/env.py) and is not our concern.
    assert EXPECTED_TABLES <= actual, f"missing: {EXPECTED_TABLES - actual}"


async def test_constraint_table_renamed(engine: AsyncEngine):
    """§7 calls it `constraint`, which is a Postgres reserved word."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
    actual = {r[0] for r in rows}
    assert "trip_constraint" in actual
    assert "constraint" not in actual


async def test_enum_labels_match_domain_models(engine: AsyncEngine):
    """Postgres must store the enum *values* ("setup"), not names ("SETUP")."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT t.typname, e.enumlabel "
                "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                "ORDER BY t.typname, e.enumsortorder"
            )
        )
    actual: dict[str, list[str]] = {}
    for typname, label in rows:
        actual.setdefault(typname, []).append(label)

    for type_name, domain_enum in EXPECTED_ENUMS.items():
        assert type_name in actual, f"enum type {type_name} not created"
        assert actual[type_name] == [m.value for m in domain_enum]

    # itinerary_version.created_by has no domain enum, it is a plain str field.
    assert actual["itinerary_created_by"] == ["agent", "user"]


async def test_embedding_is_a_pgvector_column(engine: AsyncEngine):
    async with engine.connect() as conn:
        udt = await conn.scalar(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = 'candidate_place' AND column_name = 'embedding'"
            )
        )
        dims = await conn.scalar(
            text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "WHERE a.attrelid = 'candidate_place'::regclass AND a.attname = 'embedding'"
            )
        )
    assert udt == "vector"
    assert dims == EMBEDDING_DIM


async def test_every_foreign_key_is_indexed(engine: AsyncEngine):
    """Postgres does not index FK columns automatically. Unindexed FKs make
    both JOINs and ON DELETE CASCADE do full table scans."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT conrelid::regclass::text || '.' || a.attname "
                "FROM pg_constraint c "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid "
                "  AND a.attnum = ANY(c.conkey) "
                "WHERE c.contype = 'f' "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM pg_index i "
                "    WHERE i.indrelid = c.conrelid AND a.attnum = i.indkey[0]"
                "  )"
            )
        )
    unindexed = [r[0] for r in rows]
    assert unindexed == [], f"unindexed foreign keys: {unindexed}"


async def test_vote_is_unique_per_traveler_per_candidate(engine: AsyncEngine):
    """Not in §7. Without it the §10.1 aggregator double-counts a traveler who
    revisits a card in the swipe deck."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'vote'::regclass AND contype = 'u'"
            )
        )
    assert "uq_vote_per_traveler" in {r[0] for r in rows}


async def test_itinerary_version_no_is_unique_per_trip(engine: AsyncEngine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'itinerary_version'::regclass AND contype = 'u'"
            )
        )
    assert "uq_itinerary_version_no_per_trip" in {r[0] for r in rows}


async def test_append_only_chain_uses_restrict_not_cascade(engine: AsyncEngine):
    """§7 makes the version chain append-only, so deleting a parent version or
    a candidate that a node references must fail loudly, not erase history."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT conrelid::regclass::text, conname, confdeltype "
                "FROM pg_constraint "
                "WHERE contype = 'f' AND conrelid IN ("
                "  'itinerary_version'::regclass, 'itinerary_node'::regclass)"
            )
        )
    # confdeltype: 'r' = RESTRICT, 'c' = CASCADE, 'a' = NO ACTION. Postgres
    # types it as "char", which asyncpg hands back as bytes.
    by_name = {
        conname: deltype.decode() if isinstance(deltype, bytes) else deltype
        for _, conname, deltype in rows
    }
    assert by_name["fk_itinerary_version_parent_version_id"] == "r"
    assert by_name["fk_itinerary_node_candidate_id"] == "r"
    # The node itself dies with its version: nodes have no life of their own.
    assert by_name["fk_itinerary_node_version_id"] == "c"
