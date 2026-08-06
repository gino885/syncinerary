"""Repositories: the only code allowed to talk to SQLAlchemy (CLAUDE.md §14).

API routes and graph nodes import from here, never from store/tables.py.
"""
from syncinerary.store.repositories.base import BaseRepository
from syncinerary.store.repositories.candidate import (
    CandidateBadgeRepository,
    CandidatePlaceRepository,
    VoteRepository,
)
from syncinerary.store.repositories.trip import (
    ConstraintRepository,
    TravelerRepository,
    TripRepository,
)

__all__ = [
    "BaseRepository",
    "CandidateBadgeRepository",
    "CandidatePlaceRepository",
    "ConstraintRepository",
    "TravelerRepository",
    "TripRepository",
    "VoteRepository",
]
