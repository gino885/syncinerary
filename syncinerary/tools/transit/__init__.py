"""Pluggable transit duration tool."""

from syncinerary.tools.transit.google_routes import (
    GoogleRoutesClient,
    RoutesConfigurationError,
    RoutesError,
    RoutesRateLimited,
    RoutesResponseError,
    RoutesRouteUnavailable,
    parse_duration_seconds,
)
from syncinerary.tools.transit.models import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitRequest,
    TransitUnavailable,
    choose_mode,
    haversine_km,
)
from syncinerary.tools.transit.provider import TransitProviderName, make_transit_client
from syncinerary.tools.transit.transitous import (
    TransitousClient,
    TransitousConfigurationError,
    TransitousError,
    TransitousRateLimited,
    TransitousResponseError,
    TransitousRouteUnavailable,
)

__all__ = [
    "GoogleRoutesClient",
    "PairwiseTransitRequest",
    "RoutesConfigurationError",
    "RoutesError",
    "RoutesRateLimited",
    "RoutesResponseError",
    "RoutesRouteUnavailable",
    "TransitDuration",
    "TransitLocation",
    "TransitMatrix",
    "TransitMode",
    "TransitProviderName",
    "TransitRequest",
    "TransitUnavailable",
    "TransitousClient",
    "TransitousConfigurationError",
    "TransitousError",
    "TransitousRateLimited",
    "TransitousResponseError",
    "TransitousRouteUnavailable",
    "choose_mode",
    "haversine_km",
    "make_transit_client",
    "parse_duration_seconds",
]
