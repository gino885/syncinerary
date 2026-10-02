"""Resolve the creator-funded credential for trip-scoped model work."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.harness import CreatorCredentialUnavailable, require_anthropic_api_key
from syncinerary.store.repositories import AccountRepository, AnthropicCredentialRepository


class AnthropicConsentUnavailable(CreatorCredentialUnavailable):
    """One or more account members have not approved Anthropic sharing."""


@asynccontextmanager
async def trip_creator_credential_scope(
    session: AsyncSession,
    trip_id: UUID,
) -> AsyncIterator[None]:
    """Use the creator key, or mark model access unavailable for owned trips.

    Pre-account legacy and eval trips keep the explicit server fallback. Once
    a trip has an account owner, it can never spend that fallback key.
    """
    repository = AnthropicCredentialRepository(session)
    account_id = await repository.account_for_trip_creator(trip_id)
    if account_id is None:
        yield
        return
    missing = await AccountRepository(session).missing_anthropic_consent_for_trip(
        trip_id
    )
    if missing:
        raise AnthropicConsentUnavailable(
            "Every trip member must approve Anthropic data sharing in AI privacy"
        )
    api_key = await repository.reveal(account_id)
    with require_anthropic_api_key(api_key):
        yield
