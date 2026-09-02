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
