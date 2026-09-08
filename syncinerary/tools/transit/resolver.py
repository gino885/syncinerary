"""The transit chain: ask each provider only about what the last one missed.

A missing arc is not a slow leg. In the Stage 2 routing circuit it says "these
two places cannot be visited on the same day", which is a far stronger claim
than any provider is entitled to make on its own. One Sapporo day lost four of
its five stops to exactly that: every pair came back unroutable from the single
configured provider, and the day shipped holding one stop and 645 spare
minutes.

So a provider that answers "no route", a provider that returns HTTP 500, and a
provider with no coverage in this country are all the same instruction here:
ask the next one. Only when every applicable provider has been asked does the
conservative distance estimate apply, and only past its ceiling is an arc
finally called unroutable.

Cost discipline is what makes the chain affordable. The primary is asked for
the whole day in one matrix request; every provider after it is asked about the
leftover arcs only, over only the locations those arcs touch.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, Self

from syncinerary.obs.tracing import get_tracer
from syncinerary.tools.transit.errors import TransitFailureKind, TransitProviderError
from syncinerary.tools.transit.estimate import estimated_transit_leg
from syncinerary.tools.transit.models import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitRoutingStatus,
    TransitUnavailable,
    choose_mode,
)

logger = logging.getLogger(__name__)

#: What the counters call each position in the chain. Beyond the third,
#: providers are all counted as "regional" because that is what they are.
ROLE_NAMES = ("primary", "secondary", "regional")

_ESTIMATED_PROVIDER = "estimated"


class TransitProvider(Protocol):
    """What the resolver needs from an adapter. Deliberately narrow."""

    name: str

    async def prefetch_pairwise(
        self, request: PairwiseTransitRequest
    ) -> TransitMatrix: ...

    async def aclose(self) -> None: ...


@dataclass
class TransitResolutionStats:
    """Where each arc's answer came from, for one resolver's lifetime.

    Kept so "we added a provider" can be checked against "the provider
    actually reduced the estimated and missing arcs", which are not the same
    claim. Counts are arc resolutions rather than distinct arcs: a day
    re-solved during a top-up round asks again, and that repeat is real work
    worth seeing.
    """

    routed: Counter[str] = field(default_factory=Counter)
    no_route: Counter[str] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)
    estimated: int = 0
    unroutable: int = 0

    def as_metrics(self) -> dict[str, int]:
        """Flat counter names, suitable for span attributes or a log line."""
        metrics: dict[str, int] = {}
        for role, count in self.routed.items():
            metrics[f"transit.{role}.routed"] = count
        for role, count in self.no_route.items():
            metrics[f"transit.{role}.no_route"] = count
        for key, count in self.errors.items():
            metrics[f"transit.{key}"] = count
        metrics["transit.estimated"] = self.estimated
        metrics["transit.unroutable"] = self.unroutable
        return metrics


def _role(index: int) -> str:
    return ROLE_NAMES[min(index, len(ROLE_NAMES) - 1)]


def _pair_key(origin: TransitLocation, destination: TransitLocation) -> tuple[str, str]:
    return (origin.cache_id, destination.cache_id)


class FallbackTransitResolver:
    """Resolve a day's arcs across an ordered provider chain, then estimate.

    Satisfies the same ``prefetch_pairwise`` shape the solver already calls,
    so Stage 2 knows nothing about which providers exist or how many there are.
    """

    #: Instrumentation and the solver both read this, so keep it stable.
    name = "fallback"

    def __init__(
        self,
        providers: list[TransitProvider],
        *,
        estimate_missing: bool = True,
    ) -> None:
        if not providers:
            raise ValueError("A transit resolver needs at least one provider")
        self._providers = providers
        self._estimate_missing = estimate_missing
        self.stats = TransitResolutionStats()
        # Arcs a provider has already declined during this run. A day is
        # re-solved on every top-up round, and re-asking a per-arc fallback
        # about a leg it has already refused is the one cost worth avoiding
        # without touching the providers' own time-bucketed Redis cache.
        self._declined: set[tuple[str, tuple[str, str]]] = set()

    @property
    def providers(self) -> tuple[TransitProvider, ...]:
        """The chain, primary first. Read-only, and read by instrumentation."""
        return tuple(self._providers)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()

    @staticmethod
    def _required_pairs(request: PairwiseTransitRequest) -> list[tuple[int, int]]:
        """The directed pairs a provider is expected to route.

        Walking-cutoff pairs are excluded on purpose: no adapter routes them,
        so counting them as unresolved would send every nearby pair down the
        fallback chain to be estimated at the end anyway.
        """
        return [
            (origin_index, destination_index)
            for origin_index in range(len(request.locations))
            for destination_index in range(len(request.locations))
            if origin_index != destination_index
            and request.wants(origin_index, destination_index)
            and choose_mode(
                request.locations[origin_index],
                request.locations[destination_index],
                walking_cutoff_km=request.walking_cutoff_km,
            )
            is TransitMode.TRANSIT
        ]

    def _subrequest(
        self,
        request: PairwiseTransitRequest,
        pairs: list[tuple[int, int]],
    ) -> PairwiseTransitRequest:
        """A request over only the locations the outstanding arcs touch.

        The same departure time and window travel with it. A fallback asked
        about the morning must not answer about now.
        """
        involved = sorted({index for pair in pairs for index in pair})
        remap = {original: position for position, original in enumerate(involved)}
        return PairwiseTransitRequest(
            locations=[request.locations[index] for index in involved],
            departure_window=request.departure_window,
            departure_at=request.departure_at,
            walking_cutoff_km=request.walking_cutoff_km,
            required_pairs=[
                (remap[origin], remap[destination]) for origin, destination in pairs
            ],
        )

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        required = self._required_pairs(request)
        outstanding = list(required)
        if not outstanding:
            return TransitMatrix(legs=[])

        tracer = get_tracer()
        with tracer.start_as_current_span("transit.resolve") as span:
            span.set_attribute("transit.arcs_required", len(outstanding))
            legs: dict[tuple[int, int], TransitDuration] = {}
            last_status: dict[tuple[int, int], str] = {}

            for index, provider in enumerate(self._providers):
                if not outstanding:
                    break
                role = _role(index)
                askable = [
                    pair
                    for pair in outstanding
                    if (provider.name, self._pair_id(request, pair)) not in self._declined
                ]
                if not askable:
                    continue
                matrix = await self._ask(
                    provider,
                    request,
                    askable,
                    role=role,
                    # Only a provider that still has the entire day in front
                    # of it is handed the day. Anything narrower is a subset
                    # request over the locations those arcs touch.
                    whole_day=len(askable) == len(required)
                    and request.required_pairs is None,
                )
                if matrix is None:
                    continue

                by_pair = {
                    _pair_key(leg.origin, leg.destination): leg for leg in matrix.legs
                }
                declined = {
                    _pair_key(item.origin, item.destination): item
                    for item in matrix.unavailable
                }
                still_missing: list[tuple[int, int]] = []
                for pair in outstanding:
                    key = self._pair_id(request, pair)
                    leg = by_pair.get(key)
                    if leg is not None:
                        legs[pair] = leg
                        self.stats.routed[role] += 1
                        continue
                    if key in declined:
                        self.stats.no_route[role] += 1
                        last_status[pair] = declined[key].status
                        self._declined.add((provider.name, key))
                    still_missing.append(pair)
                outstanding = still_missing

            unavailable = self._finish(request, outstanding, legs, last_status)
            for key, value in self.stats.as_metrics().items():
                span.set_attribute(key, value)

        if outstanding or self.stats.estimated:
            logger.info("transit resolution %s", self.stats.as_metrics())
        return TransitMatrix(
            legs=list(legs.values()),
            unavailable=unavailable,
        )

    @staticmethod
    def _pair_id(
        request: PairwiseTransitRequest, pair: tuple[int, int]
    ) -> tuple[str, str]:
        origin_index, destination_index = pair
        return _pair_key(
            request.locations[origin_index],
            request.locations[destination_index],
        )

    async def _ask(
        self,
        provider: TransitProvider,
        request: PairwiseTransitRequest,
        pairs: list[tuple[int, int]],
        *,
        role: str,
        whole_day: bool,
    ) -> TransitMatrix | None:
        """One provider's answer, or ``None`` when it could not give one.

        Every failure kind lands here identically: record it and let the
        caller move on. The kinds are kept apart in the counters because
        "this provider has no coverage here" and "this provider is down"
        need different responses from a human, even though the chain treats
        them the same in the moment.
        """
        # The primary sees the day as one matrix request. Everything after it
        # sees only the arcs still missing, over only the locations they touch.
        subrequest = request if whole_day else self._subrequest(request, pairs)
        try:
            matrix = await provider.prefetch_pairwise(subrequest)
        except TransitProviderError as exc:
            kind = getattr(exc, "kind", TransitFailureKind.PROVIDER_ERROR)
            self.stats.errors[f"{role}.{kind.value}"] += 1
            logger.warning(
                "transit provider %s failed (%s), falling through: %s",
                provider.name,
                kind.value,
                exc,
            )
            return None
        # An adapter that leaks a transport error rather than wrapping it must
        # still not take the itinerary down with it.
        except (OSError, TimeoutError) as exc:  # pragma: no cover - defensive
            self.stats.errors[f"{role}.{TransitFailureKind.PROVIDER_ERROR.value}"] += 1
            logger.warning(
                "transit provider %s raised %s, falling through",
                provider.name,
                type(exc).__name__,
            )
            return None
        # A subrequest is reindexed, but legs carry locations rather than
        # indexes, so the caller matches them back by cache id.
        return matrix

    def _finish(
        self,
        request: PairwiseTransitRequest,
        outstanding: list[tuple[int, int]],
        legs: dict[tuple[int, int], TransitDuration],
        last_status: dict[tuple[int, int], str],
    ) -> list[TransitUnavailable]:
        """Estimate what is left, and admit the rest is genuinely unroutable."""
        unavailable: list[TransitUnavailable] = []
        for pair in outstanding:
            origin = request.locations[pair[0]]
            destination = request.locations[pair[1]]
            estimate = (
                estimated_transit_leg(origin, destination)
                if self._estimate_missing
                else None
            )
            if estimate is None:
                self.stats.unroutable += 1
                unavailable.append(
                    TransitUnavailable(
                        origin=origin,
                        destination=destination,
                        mode=TransitMode.TRANSIT,
                        departure_window=request.departure_window,
                        status=last_status.get(pair, "NO_PROVIDER_ROUTE"),
                        detail="no provider routed this pair and it is beyond estimate range",
                    )
                )
                continue
            minutes, mode = estimate
            self.stats.estimated += 1
            legs[pair] = TransitDuration(
                origin=origin,
                destination=destination,
                mode=mode,
                departure_window=request.departure_window,
                duration_seconds=minutes * 60,
                duration_minutes=minutes,
                provider=_ESTIMATED_PROVIDER,
                routing_status=TransitRoutingStatus.ESTIMATED,
            )
        return unavailable


__all__ = [
    "FallbackTransitResolver",
    "TransitProvider",
    "TransitResolutionStats",
]
