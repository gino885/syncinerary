"""Group trip persistence: accounts, sessions, invites, and the trip thread.

Email credentials are managed by EmailAccountRepository. Public account models
exclude secrets; session tokens are hashed before storage.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import UUID

from sqlalchemy import delete, or_, select, update

from syncinerary.domain.models import (
    Account,
    AccountSession,
    TripInvite,
    TripMessage,
)
from syncinerary.privacy import ANTHROPIC_CONSENT_VERSION
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository

SESSION_TTL = timedelta(days=30)
INVITE_TTL = timedelta(days=14)
# Crockford-ish: no I, L, O, U, so a code read aloud or retyped from a
# screenshot does not turn into a different trip.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 8


def _now() -> datetime:
    return datetime.now(UTC)


def generate_invite_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


class AccountRepository(BaseRepository[tables.Account, Account]):
    table = tables.Account
    model = Account

    async def find_by_handle(self, handle: str) -> Account | None:
        found = await self.list_where(tables.Account.handle == handle.casefold())
        return found[0] if found else None

    async def upsert_by_handle(self, *, display_name: str, handle: str) -> Account:
        """Sign-in for a stub identity: the handle is the whole credential.

        Deliberately not a security boundary. It exists so a person keeps one
        identity across trips, which is what invites and chat authorship need.
        """
        existing = await self.find_by_handle(handle)
        if existing is not None:
            return existing
        return await self.add(
            Account(display_name=display_name, handle=handle.casefold())
        )

    async def grant_anthropic_consent(self, account_id: UUID) -> Account:
        row = await self.session.scalar(
            update(self.table)
            .where(self.table.id == account_id)
            .values(
                anthropic_consent_version=ANTHROPIC_CONSENT_VERSION,
                anthropic_consent_at=_now(),
            )
            .returning(self.table)
        )
        if row is None:
            raise ValueError("Account no longer exists")
        return self.to_model(row)

    async def revoke_anthropic_consent(self, account_id: UUID) -> Account:
        row = await self.session.scalar(
            update(self.table)
            .where(self.table.id == account_id)
            .values(anthropic_consent_version=None, anthropic_consent_at=None)
            .returning(self.table)
        )
        if row is None:
            raise ValueError("Account no longer exists")
        return self.to_model(row)

    async def missing_anthropic_consent_for_trip(self, trip_id: UUID) -> list[str]:
        statement = (
            select(tables.Traveler.name)
            .join(self.table, self.table.id == tables.Traveler.account_id)
            .where(
                tables.Traveler.trip_id == trip_id,
                (
                    self.table.anthropic_consent_version
                    != ANTHROPIC_CONSENT_VERSION
                )
                | self.table.anthropic_consent_version.is_(None)
                | self.table.anthropic_consent_at.is_(None),
            )
            .order_by(tables.Traveler.name)
        )
        return list(await self.session.scalars(statement))

    async def attachment_storage_keys_for_account(self, account_id: UUID) -> set[str]:
        """Return screenshot objects that account deletion must remove."""
        travelers = list(
            await self.session.scalars(
                select(tables.Traveler).where(
                    tables.Traveler.account_id == account_id
                )
            )
        )
        if not travelers:
            return set()
        traveler_ids = {traveler.id for traveler in travelers}
        owned_trip_ids = set(
            await self.session.scalars(
                select(tables.Trip.id).where(
                    tables.Trip.created_by.in_(traveler_ids)
                )
            )
        )
        values = await self.session.scalars(
            select(tables.SourceAttachment.screenshot_storage_key).where(
                tables.SourceAttachment.screenshot_storage_key.is_not(None),
                or_(
                    tables.SourceAttachment.traveler_id.in_(traveler_ids),
                    tables.SourceAttachment.trip_id.in_(owned_trip_ids),
                ),
            )
        )
        return {value for value in values if value}

    async def delete_personal_data(self, account_id: UUID) -> list[UUID]:
        """Delete owned trips and remove this person from trips they joined.

        Shared venue facts may remain, but account identifiers, messages,
        profiles, votes, attachments, private model snapshots, and source
        attribution are removed. Returned trip IDs identify graph checkpoints
        that the API must delete through the checkpointer.
        """
        travelers = list(
            await self.session.scalars(
                select(tables.Traveler).where(
                    tables.Traveler.account_id == account_id
                )
            )
        )
        traveler_ids = {traveler.id for traveler in travelers}
        trip_ids = {traveler.trip_id for traveler in travelers}
        if not traveler_ids:
            await self.session.execute(
                delete(self.table).where(self.table.id == account_id)
            )
            return []

        owned_trip_ids = set(
            await self.session.scalars(
                select(tables.Trip.id).where(
                    tables.Trip.created_by.in_(traveler_ids)
                )
            )
        )
        joined_trip_ids = trip_ids - owned_trip_ids

        if owned_trip_ids:
            await self.session.execute(
                delete(tables.GatherRun).where(
                    tables.GatherRun.trip_id.in_(owned_trip_ids)
                )
            )
            await self.session.execute(
                delete(tables.ChecklistItem).where(
                    tables.ChecklistItem.trip_id.in_(owned_trip_ids)
                )
            )
            await self.session.execute(
                delete(tables.Trip).where(tables.Trip.id.in_(owned_trip_ids))
            )

        remaining_ids = {
            traveler.id
            for traveler in travelers
            if traveler.trip_id in joined_trip_ids
        }
        if remaining_ids:
            attachment_ids = {
                str(value)
                for value in await self.session.scalars(
                    select(tables.SourceAttachment.id).where(
                        tables.SourceAttachment.traveler_id.in_(remaining_ids)
                    )
                )
            }
            await self.session.execute(
                delete(tables.TripMessage).where(
                    tables.TripMessage.traveler_id.in_(remaining_ids)
                )
            )
            await self.session.execute(
                delete(tables.TripInvite).where(
                    tables.TripInvite.created_by_traveler_id.in_(remaining_ids)
                )
            )
            await self.session.execute(
                delete(tables.GatherRun).where(
                    tables.GatherRun.trip_id.in_(joined_trip_ids)
                )
            )
            await self._scrub_shared_references(
                joined_trip_ids,
                remaining_ids,
                attachment_ids,
            )
            await self.session.execute(
                update(tables.Trip)
                .where(tables.Trip.created_by.in_(remaining_ids))
                .values(created_by=None)
            )
            await self.session.execute(
                delete(tables.Traveler).where(
                    tables.Traveler.id.in_(remaining_ids)
                )
            )

        await self.session.execute(
            delete(self.table).where(self.table.id == account_id)
        )
        await self.session.flush()
        return sorted(trip_ids, key=str)

    async def _scrub_shared_references(
        self,
        trip_ids: set[UUID],
        traveler_ids: set[UUID],
        attachment_ids: set[str],
    ) -> None:
        id_strings = {str(value) for value in traveler_ids}
        shortlists = list(
            await self.session.scalars(
                select(tables.ShortlistState).where(
                    tables.ShortlistState.trip_id.in_(trip_ids)
                )
            )
        )
        for shortlist in shortlists:
            shortlist.confirmed_by = [
                value
                for value in shortlist.confirmed_by
                if str(value) not in id_strings
            ]

        nodes = list(
            await self.session.scalars(
                select(tables.ItineraryNode)
                .join(
                    tables.ItineraryVersion,
                    tables.ItineraryVersion.id == tables.ItineraryNode.version_id,
                )
                .where(tables.ItineraryVersion.trip_id.in_(trip_ids))
            )
        )
        for node in nodes:
            node.notes_for_travelers = {
                key: value
                for key, value in node.notes_for_travelers.items()
                if str(key) not in id_strings
            }

        candidates = list(
            await self.session.scalars(
                select(tables.CandidatePlace).where(
                    tables.CandidatePlace.trip_id.in_(trip_ids)
                )
            )
        )
        for candidate in candidates:
            candidate.sources = [
                source
                for source in candidate.sources
                if str(source.get("by")) not in id_strings
            ]
            enrichment = dict(candidate.enrichment)
            if str(enrichment.get("attachment_id")) in attachment_ids:
                for key in (
                    "attachment_id",
                    "input_type",
                    "platform",
                    "source_url",
                    "platform_preview_url",
                    "source_description",
                ):
                    enrichment.pop(key, None)
                candidate.enrichment = enrichment


class AccountSessionRepository(BaseRepository[tables.AccountSession, AccountSession]):
    table = tables.AccountSession
    model = AccountSession

    async def issue(self, account_id: UUID) -> AccountSession:
        token = secrets.token_urlsafe(32)
        stored = await self.add(AccountSession(
            token=self.digest(token), account_id=account_id,
            expires_at=_now() + SESSION_TTL,
        ))
        return stored.model_copy(update={"token": token})

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def resolve(self, token: str) -> AccountSession | None:
        found = await self.list_where(tables.AccountSession.token == self.digest(token))
        return found[0] if found and found[0].expires_at > _now() else None

    async def revoke(self, token: str) -> None:
        await self.session.execute(delete(tables.AccountSession).where(
            tables.AccountSession.token == self.digest(token)))

    async def revoke_all(self, account_id: UUID) -> None:
        await self.session.execute(delete(tables.AccountSession).where(
            tables.AccountSession.account_id == account_id))


class TripInviteRepository(BaseRepository[tables.TripInvite, TripInvite]):
    table = tables.TripInvite
    model = TripInvite

    async def create_for_trip(
        self,
        *,
        trip_id: UUID,
        created_by_traveler_id: UUID,
        max_uses: int = 20,
    ) -> TripInvite:
        return await self.add(
            TripInvite(
                trip_id=trip_id,
                code=generate_invite_code(),
                created_by_traveler_id=created_by_traveler_id,
                expires_at=_now() + INVITE_TTL,
                max_uses=max_uses,
            )
        )

    async def find_by_code(self, code: str) -> TripInvite | None:
        found = await self.list_where(tables.TripInvite.code == code.upper())
        return found[0] if found else None

    async def claim(self, invite_id: UUID) -> TripInvite | None:
        """Consume one use, refusing to exceed the cap.

        The bound is in the WHERE clause rather than in Python because two
        people opening the same link at once would both read uses < max and
        both write uses + 1. The database decides, so only one wins.
        """
        stmt = (
            update(tables.TripInvite)
            .where(
                tables.TripInvite.id == invite_id,
                tables.TripInvite.revoked_at.is_(None),
                tables.TripInvite.uses < tables.TripInvite.max_uses,
                tables.TripInvite.expires_at > _now(),
            )
            .values(uses=tables.TripInvite.uses + 1)
            .returning(tables.TripInvite)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None

    async def revoke(self, invite_id: UUID) -> TripInvite | None:
        stmt = (
            update(tables.TripInvite)
            .where(tables.TripInvite.id == invite_id)
            .values(revoked_at=_now())
            .returning(tables.TripInvite)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None

    async def list_for_trip(self, trip_id: UUID) -> list[TripInvite]:
        return await self.list_where(
            tables.TripInvite.trip_id == trip_id,
            order_by=tables.TripInvite.created_at,
        )


class TripMessageRepository(BaseRepository[tables.TripMessage, TripMessage]):
    table = tables.TripMessage
    model = TripMessage

    column_aliases: ClassVar[dict[str, str]] = {}

    async def list_for_trip(self, trip_id: UUID, *, limit: int = 200) -> list[TripMessage]:
        """Thread history, oldest first, capped so a long thread cannot
        become an unbounded response."""
        messages = await self.list_where(
            tables.TripMessage.trip_id == trip_id,
            order_by=tables.TripMessage.created_at,
        )
        return messages[-limit:]


__all__ = [
    "AccountRepository",
    "AccountSessionRepository",
    "TripInviteRepository",
    "TripMessageRepository",
    "generate_invite_code",
]
