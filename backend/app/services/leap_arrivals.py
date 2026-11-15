"""Shared source of call-arrival timing for the audit generator and the simulator.

HONESTY NOTE: the hour and day weights below are FITTED to reproduce the brief's
coverage totals. They are NOT copied from LEAP's published tables. If someone
extracts the real tables from the LEAP PDF, only this file changes.
"""

import math
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import CallType, Incident

# Share of calls arriving in each clock hour (0-23). Sums to 1.
HOUR_WEIGHTS = (
    0.058, 0.050, 0.018, 0.016, 0.014, 0.014, 0.018, 0.020,
    0.030, 0.036, 0.040, 0.042, 0.044, 0.046, 0.046, 0.046,
    0.050, 0.055, 0.057, 0.058,
    0.060, 0.062, 0.062, 0.058,
)

# Share of calls per weekday, Monday=0 ... Sunday=6. Sums to 1.
DAY_WEIGHTS = (0.132,) * 5 + (0.180, 0.160)

# Illustrative mix, not LEAP data.
CALL_TYPE_WEIGHTS = (
    (CallType.WELLBEING_CHECK, 0.30),
    (CallType.DISTURBANCE, 0.27),
    (CallType.SUSPICIOUS, 0.18),
    (CallType.NOISE_COMPLAINT, 0.15),
    (CallType.OTHER, 0.10),
)

TIMEZONE = ZoneInfo("America/New_York")


def coverage(weekdays, start_hour: int, end_hour: int) -> float:
    """Share of calls arriving on `weekdays` (0=Mon) during [start_hour, end_hour)."""
    return sum(DAY_WEIGHTS[d] for d in set(weekdays)) * sum(
        HOUR_WEIGHTS[start_hour:end_hour]
    )


def duration_multiplier(rng: random.Random, cv: float = 0.5) -> float:
    """Lognormal multiplier on average call duration (mean 1, coefficient of
    variation `cv`), clipped to 0.25-4, so the mean lands just under 1."""
    sigma = math.sqrt(math.log(1 + cv**2))
    return min(4.0, max(0.25, rng.lognormvariate(-sigma**2 / 2, sigma)))


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth's method; fine for the small daily rates used here.
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def generate_calls(
    rng: random.Random,
    start_day: date,
    weeks: int,
    calls_per_week: float = 47,
) -> list[Incident]:
    """Arrivals sorted by time, with all four safety answers False.

    LEAP's ~2,420 appropriate calls per year (~47/week) are post-screening,
    so every generated call has already passed the safety questions.
    """
    types, type_weights = zip(*CALL_TYPE_WEIGHTS)
    calls = []

    for offset in range(7 * weeks):
        day = start_day + timedelta(days=offset)
        count = _poisson(rng, calls_per_week * DAY_WEIGHTS[day.weekday()])

        for _ in range(count):
            hour = rng.choices(range(24), HOUR_WEIGHTS)[0]
            calls.append(
                Incident(
                    call_type=rng.choices(types, type_weights)[0],
                    weapon_present=False,
                    violence=False,
                    injury=False,
                    immediate_danger=False,
                    timestamp=datetime(
                        day.year, day.month, day.day, hour,
                        rng.randrange(60), rng.randrange(60),
                        tzinfo=TIMEZONE,
                    ),
                )
            )

    return sorted(calls, key=lambda c: c.timestamp)
