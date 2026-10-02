"""Deterministic group interests shared by social and profile discovery."""
from collections import Counter
from uuid import UUID

from syncinerary.domain.models import Traveler
from syncinerary.tools.fetch.social import interest_slug

GROUP_INTEREST_LIMIT = 5


def normalized_interests(traveler: Traveler) -> set[str]:
    raw = traveler.profile.get("interests")
    if not isinstance(raw, list):
        return set()
    return {
        interest_slug(item).replace("_", " ").strip()
        for item in raw
        if isinstance(item, str) and interest_slug(item).strip("_")
    }


def traveler_interests(travelers: list[Traveler]) -> list[str]:
    """Top five by member count; alphabetical ties are independent of join order.

    Count each member once per interest, even if a profile or caller repeats
    an entry. Personal profiles and hard dietary constraints stay intact.
    """
    by_member: dict[UUID, set[str]] = {}
    for traveler in travelers:
        by_member.setdefault(traveler.id, set()).update(normalized_interests(traveler))
    counts = Counter(interest for interests in by_member.values() for interest in interests)
    return sorted(counts, key=lambda interest: (-counts[interest], interest))[:GROUP_INTEREST_LIMIT]
