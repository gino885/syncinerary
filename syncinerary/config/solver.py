"""Solver defaults. See CLAUDE.md §16."""

DAILY_FATIGUE_BUDGET = 8
WALKING_MINUTES_PER_DAY = 90
DAY_DURATION_CAP_HOURS = 12
DEFAULT_DAY_START_HOUR = 8
# Extended past the original 20:00 so a dinner seating fits inside the day
# window. The 12-hour active cap below still binds, so days do not get longer.
DEFAULT_DAY_END_HOUR = 21
M1_DESTINATION_TIMEZONE = "Asia/Tokyo"

# M1 transit mode selection. Nearby pairs use walking directions; longer
# pairs use public transit. The project owner chose 2 km as the cutoff.
NEARBY_WALKING_KM = 2.0

FATIGUE_COST_LOW = 1
FATIGUE_COST_MED = 2
FATIGUE_COST_HIGH = 3


# Meal slotting (CLAUDE.md section 11.2, "match meal categories to meal times").
# Each window is (earliest_start_hour, latest_end_hour) on the local clock.
# Breakfast is optional: it is rewarded when it costs nothing, never forced.
BREAKFAST_WINDOW_HOURS = (7, 10)
LUNCH_WINDOW_HOURS = (11, 15)
DINNER_WINDOW_HOURS = (17, 21)

MEAL_WINDOWS = {
    "breakfast": BREAKFAST_WINDOW_HOURS,
    "lunch": LUNCH_WINDOW_HOURS,
    "dinner": DINNER_WINDOW_HOURS,
}
REQUIRED_MEALS = ("lunch", "dinner")
OPTIONAL_MEALS = ("breakfast",)

# Day composition. A day is sights first with meals around them, so the food
# quota is a floor for lunch and dinner and a ceiling that stops restaurants
# taking slots the sightseeing needs. Every quota degrades to what the pool can
# actually supply rather than making the day infeasible.
FOOD_PER_DAY_TARGET = 3
MEALS_PER_DAY_MIN = 2
FOOD_PER_DAY_MAX = 3
ATTRACTIONS_PER_DAY_MIN = 3
ATTRACTIONS_PER_DAY_TARGET = 4

# Day fullness (make-up plan). A day below this many stops can borrow a selected
# candidate that did not fit another day, nearest-first, then be re-solved.
# Three sights plus lunch and dinner.
MIN_STOPS_PER_DAY = 5
# Candidates offered to one thin day per round, and how many rounds run. Both
# are bounded so the top-up cannot grow the transit fan-out without limit.
TOPUP_CANDIDATES_PER_ROUND = 4
TOPUP_MAX_ROUNDS = 2
# How far a stand-in may sit from the centre of the day it is offered to.
# Without this the meal weighting will happily send a day across the region
# for dinner, and take the restaurant the next day needed while it is there.
TOPUP_MAX_DETOUR_KM = 12.0
