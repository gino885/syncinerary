"""The publication grid, shared by solver and API validation."""

from datetime import time
from math import ceil

SCHEDULE_QUANTUM_MINUTES = 30


def ceil_slot(minutes: float) -> int:
    return ceil(minutes / SCHEDULE_QUANTUM_MINUTES) * SCHEDULE_QUANTUM_MINUTES


def validate_clock(value: time) -> time:
    if value.minute % SCHEDULE_QUANTUM_MINUTES or value.second or value.microsecond:
        raise ValueError("Itinerary times must use 30-minute boundaries")
    return value
