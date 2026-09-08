"""Google Routes and Redis cache settings for the transit tool."""

ROUTES_MATRIX_URL = (
    "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
)
ROUTES_FIELD_MASK = (
    "originIndex,destinationIndex,status,condition,distanceMeters,duration"
)
ROUTES_TIMEOUT_SECONDS = 20.0

TRANSITOUS_ONE_TO_MANY_URL = (
    "https://api.transitous.org/api/experimental/one-to-many-intermodal"
)
TRANSITOUS_TIMEOUT_SECONDS = 30.0
TRANSITOUS_MAX_TRAVEL_MINUTES = 180
TRANSITOUS_USER_AGENT = "Syncinerary/0.1.0 (https://github.com/gino885/syncinerary)"

TRANSIT_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7
REDIS_CONNECT_TIMEOUT_SECONDS = 2.0
REDIS_SOCKET_TIMEOUT_SECONDS = 5.0
REDIS_MAX_CONNECTIONS = 20

# HERE Transit v8. Only used as a fallback for arcs the primary provider could
# not route, which is what makes a per-arc API affordable: HERE publishes no
# transit matrix endpoint, so a full day's matrix through it would be N^2 calls.
HERE_TRANSIT_ROUTES_URL = "https://transit.router.hereapi.com/v8/routes"
HERE_TIMEOUT_SECONDS = 15.0
#: Most arcs a single HERE fallback request may spend. A day that needs more
#: than this has a primary-provider problem the estimate should absorb instead.
HERE_MAX_ARCS_PER_REQUEST = 24
#: Concurrent HERE calls. Small enough to stay well inside a freemium plan's
#: requests-per-second, large enough that a dozen arcs is not a dozen timeouts.
HERE_MAX_CONCURRENCY = 4
