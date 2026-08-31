"""Candidate place, vote and delegate badge repositories."""
from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from syncinerary.domain.models import CandidateBadge, CandidatePlace, CandidateType, Vote
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class CandidatePlaceRepository(BaseRepository[tables.CandidatePlace, CandidatePlace]):
    """The candidate pool for a trip.

    Note that `embedding` is a column but not a domain field. It is dedup
    machinery (§8.4) that nothing outside store/ reads, so it stays out of the
    model the graph passes around; the column is nullable and left NULL until
    M3 enrichment fills it.
    """

    table = tables.CandidatePlace
    model = CandidatePlace
    jsonb_fields = frozenset({"hours_by_weekday", "sources", "enrichment", "trending_signals"})

    async def list_for_trip(self, trip_id: UUID) -> list[CandidatePlace]:
        return await self.list_where(
            tables.CandidatePlace.trip_id == trip_id,
            order_by=tables.CandidatePlace.name_canonical,
        )

    async def list_swipeable(self, trip_id: UUID) -> list[CandidatePlace]:
        """Attractions and food only.

        CLAUDE.md §8.6: lodging never enters the swipe deck. It is chosen by
        the solver after shortlist confirmation, so it is gathered and stored
        like any other card but filtered out here.
        """
        return await self.list_where(
            tables.CandidatePlace.trip_id == trip_id,
            tables.CandidatePlace.type != CandidateType.LODGING,
            order_by=tables.CandidatePlace.name_canonical,
        )

    async def list_by_type(
        self, trip_id: UUID, candidate_type: CandidateType
    ) -> list[CandidatePlace]:
        return await self.list_where(
            tables.CandidatePlace.trip_id == trip_id,
            tables.CandidatePlace.type == candidate_type,
            order_by=tables.CandidatePlace.name_canonical,
        )

    async def list_by_ids(self, candidate_ids: list[UUID]) -> list[CandidatePlace]:
        """Fetch a specific set, e.g. the shortlist, in one query.

        Returned in the caller's order: the shortlist is ordered (§7) and the
        solver depends on that, whereas SQL makes no ordering promise for IN.
        """
        if not candidate_ids:
            return []
        found = await self.list_where(tables.CandidatePlace.id.in_(candidate_ids))
        by_id = {c.id: c for c in found}
        return [by_id[cid] for cid in candidate_ids if cid in by_id]

    async def count_for_trip(self, trip_id: UUID) -> int:
        return len(await self.list_for_trip(trip_id))


class VoteRepository(BaseRepository[tables.Vote, Vote]):
    table = tables.Vote
    model = Vote
    jsonb_fields = frozenset({"note_parsed"})

    async def upsert(self, vote: Vote) -> Vote:
        """Record a swipe, replacing this traveler's earlier one if any.

        The swipe deck lets someone revisit a card. Inserting blindly would
        make the §10.1 aggregator count one person twice, so this writes
        through the unique (candidate_id, traveler_id) key. The stored id is
        left alone on conflict: the vote keeps its original identity and only
        its content changes.
        """
        values = self.to_row_values(vote)
        stmt = (
            pg_insert(tables.Vote)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_vote_per_traveler",
                set_={
                    "signal": values["signal"],
                    "note_text": values["note_text"],
                    "note_parsed": values["note_parsed"],
                },
            )
            .returning(tables.Vote)
        )
        row = (await self.session.scalars(stmt)).one()
        return self.to_model(row)

    async def list_for_candidate(self, candidate_id: UUID) -> list[Vote]:
        return await self.list_where(tables.Vote.candidate_id == candidate_id)

    async def list_for_trip(self, trip_id: UUID) -> list[Vote]:
        """Every vote cast on any candidate in this trip.

        Vote has no trip_id of its own (§7), so this joins through
        candidate_place. The aggregator reads the whole set at once.
        """
        stmt = (
            select(tables.Vote)
            .join(tables.CandidatePlace, tables.CandidatePlace.id == tables.Vote.candidate_id)
            .where(tables.CandidatePlace.trip_id == trip_id)
        )
        result = await self.session.scalars(stmt)
        return [self.to_model(row) for row in result.all()]

    async def list_for_traveler(self, traveler_id: UUID) -> list[Vote]:
        return await self.list_where(tables.Vote.traveler_id == traveler_id)


class CandidateBadgeRepository(BaseRepository[tables.CandidateBadge, CandidateBadge]):
    """Delegate badges (§9.1). Written in batch before swiping starts.

    Not used until M4; the repository exists now so the store layer covers
    every table in §7 rather than growing a hole to fill later.
    """

    table = tables.CandidateBadge
    model = CandidateBadge
    column_aliases: ClassVar[dict[str, str]] = {}

    async def list_for_candidate(self, candidate_id: UUID) -> list[CandidateBadge]:
        return await self.list_where(tables.CandidateBadge.candidate_id == candidate_id)

    async def list_for_traveler_on_trip(self, traveler_id: UUID) -> list[CandidateBadge]:
        """A traveler sees only their own badges, never anyone else's."""
        return await self.list_where(tables.CandidateBadge.traveler_id == traveler_id)

    async def replace_for_trip(
        self,
        trip_id: UUID,
        badges: list[CandidateBadge],
    ) -> list[CandidateBadge]:
        """Replace one trip's pre-swipe badge batch atomically.

        Removing the old rows first matters when a refreshed model response
        changes a previous warning to no badge. Both statements run in the
        caller's short write transaction, after all model calls have ended.
        """
        candidate_ids = select(tables.CandidatePlace.id).where(
            tables.CandidatePlace.trip_id == trip_id
        )
        await self.session.execute(
            sa_delete(tables.CandidateBadge).where(
                tables.CandidateBadge.candidate_id.in_(candidate_ids)
            )
        )
        return await self.add_many(badges)
