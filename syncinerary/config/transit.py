"""Google Directions and Redis cache settings for the M1 transit tool."""

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
DIRECTIONS_TIMEOUT_SECONDS = 15.0
DIRECTIONS_MAX_CONCURRENCY = 8

TRANSIT_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7
REDIS_CONNECT_TIMEOUT_SECONDS = 2.0
REDIS_SOCKET_TIMEOUT_SECONDS = 5.0
REDIS_MAX_CONNECTIONS = 20
