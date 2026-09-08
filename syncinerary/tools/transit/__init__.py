"""Pluggable transit duration tool."""

from syncinerary.tools.transit.attribution import (
    REQUIRED_ATTRIBUTIONS,
    TransitAttribution,
    attributions_for,
)
from syncinerary.tools.transit.errors import TransitFailureKind, TransitProviderError
from syncinerary.tools.transit.estimate import estimated_transit_leg
from syncinerary.tools.transit.google_routes import (
    GoogleRoutesClient,
    RoutesConfigurationError,
    RoutesError,
    RoutesRateLimited,
    RoutesResponseError,
    RoutesRouteUnavailable,
    parse_duration_seconds,
)
from syncinerary.tools.transit.here import (
    HereConfigurationError,
    HereError,
    HereRateLimited,
    HereResponseError,
    HereRouteUnavailable,
    HereTransitClient,
)
from syncinerary.tools.transit.models import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitRequest,
    TransitRoutingStatus,
    TransitUnavailable,
    choose_mode,
    haversine_km,
)
from syncinerary.tools.transit.provider import (
    TransitProviderName,
    make_transit_client,
    transit_chain_names,
)
from syncinerary.tools.transit.registry import (
    RegionalProviderRegistry,
    TransitRegion,
    regional_provider_registry,
)
from syncinerary.tools.transit.resolver import (
    FallbackTransitResolver,
    TransitProvider,
    TransitResolutionStats,
)
from syncinerary.tools.transit.transitous import (
    TransitousClient,
    TransitousConfigurationError,
    TransitousError,
    TransitousRateLimited,
    TransitousResponseError,
    TransitousRouteUnavailable,
)

__all__ = [
    "REQUIRED_ATTRIBUTIONS",
    "FallbackTransitResolver",
    "GoogleRoutesClient",
    "HereConfigurationError",
    "HereError",
    "HereRateLimited",
    "HereResponseError",
    "HereRouteUnavailable",
    "HereTransitClient",
    "PairwiseTransitRequest",
    "RegionalProviderRegistry",
    "RoutesConfigurationError",
    "RoutesError",
    "RoutesRateLimited",
    "RoutesResponseError",
    "RoutesRouteUnavailable",
    "TransitAttribution",
    "TransitDuration",
    "TransitFailureKind",
    "TransitLocation",
    "TransitMatrix",
    "TransitMode",
    "TransitProvider",
    "TransitProviderError",
    "TransitProviderName",
    "TransitRegion",
    "TransitRequest",
    "TransitResolutionStats",
    "TransitRoutingStatus",
    "TransitUnavailable",
    "TransitousClient",
    "TransitousConfigurationError",
    "TransitousError",
    "TransitousRateLimited",
    "TransitousResponseError",
    "TransitousRouteUnavailable",
    "attributions_for",
    "choose_mode",
    "estimated_transit_leg",
    "haversine_km",
    "make_transit_client",
    "parse_duration_seconds",
    "regional_provider_registry",
    "transit_chain_names",
]
