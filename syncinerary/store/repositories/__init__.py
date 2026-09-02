"""Repositories: the only code allowed to talk to SQLAlchemy (CLAUDE.md §14).

API routes and graph nodes import from here, never from store/tables.py.
"""
from syncinerary.store.repositories.attachment import SourceAttachmentRepository
from syncinerary.store.repositories.base import BaseRepository
from syncinerary.store.repositories.candidate import (
    CandidateBadgeRepository,
    CandidatePlaceRepository,
    VoteRepository,
)
from syncinerary.store.repositories.group import (
    AccountRepository,
    AccountSessionRepository,
    TripInviteRepository,
    TripMessageRepository,
)
from syncinerary.store.repositories.itinerary import (
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ShortlistStateRepository,
    WishlistNotPlacedRepository,
)
from syncinerary.store.repositories.ops import (
    AgentRunRepository,
    EvalResultRepository,
    EvalScenarioRepository,
    ReplanEventRepository,
)
from syncinerary.store.repositories.trip import (
    ConstraintRepository,
    TravelerRepository,
    TripRepository,
)

__all__ = [
    "AccountRepository",
    "AccountSessionRepository",
    "AgentRunRepository",
    "BaseRepository",
    "CandidateBadgeRepository",
    "CandidatePlaceRepository",
    "ConstraintRepository",
    "EvalResultRepository",
    "EvalScenarioRepository",
    "ItineraryNodeRepository",
    "ItineraryVersionRepository",
    "ReplanEventRepository",
    "ShortlistStateRepository",
    "SourceAttachmentRepository",
    "TravelerRepository",
    "TripInviteRepository",
    "TripMessageRepository",
    "TripRepository",
    "VoteRepository",
    "WishlistNotPlacedRepository",
]
