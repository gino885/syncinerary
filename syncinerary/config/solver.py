"""Solver defaults. See CLAUDE.md §16."""

DAILY_FATIGUE_BUDGET = 8
WALKING_MINUTES_PER_DAY = 90
DAY_DURATION_CAP_HOURS = 12
DEFAULT_DAY_START_HOUR = 8
DEFAULT_DAY_END_HOUR = 20
M1_DESTINATION_TIMEZONE = "Asia/Tokyo"

# M1 transit mode selection. Nearby pairs use walking directions; longer
# pairs use public transit. The project owner chose 2 km as the cutoff.
NEARBY_WALKING_KM = 2.0

FATIGUE_COST_LOW = 1
FATIGUE_COST_MED = 2
FATIGUE_COST_HIGH = 3
