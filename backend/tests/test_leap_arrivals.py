import random
from collections import Counter
from datetime import date

import pytest

from app.services.leap_arrivals import (
    CALL_TYPE_WEIGHTS,
    DAY_WEIGHTS,
    HOUR_WEIGHTS,
    coverage,
    duration_multiplier,
    generate_calls,
)

WEEKDAYS, ALL_DAYS = range(5), range(7)


def test_weights_sum_to_one():
    assert sum(HOUR_WEIGHTS) == pytest.approx(1)
    assert sum(DAY_WEIGHTS) == pytest.approx(1)
    assert sum(w for _, w in CALL_TYPE_WEIGHTS) == pytest.approx(1)
    assert len(HOUR_WEIGHTS) == 24 and len(DAY_WEIGHTS) == 7


# The brief's coverage table. coverage() cannot wrap past midnight (neither can
# the simulator), so the 3 AM to midnight row is the longest same-day window
# that also reaches 87%; LEAP's real schedule is checked as a direct sum below.
@pytest.mark.parametrize(
    "days, start, end, expected",
    [
        (WEEKDAYS, 8, 16, 0.22),
        (WEEKDAYS, 8, 20, 0.36),
        (ALL_DAYS, 8, 20, 0.55),
        (ALL_DAYS, 3, 24, 0.87),
    ],
)
def test_coverage_matches_brief(days, start, end, expected):
    assert coverage(days, start, end) == pytest.approx(expected, abs=0.01)


def test_leap_9am_to_2am_every_day_covers_87_percent():
    # The brief's fourth row: every day, 9 AM to 2 AM (hours 9-23 plus 0 and 1).
    assert sum(HOUR_WEIGHTS[9:24]) + HOUR_WEIGHTS[0] + HOUR_WEIGHTS[1] == (
        pytest.approx(0.87, abs=0.01)
    )
    # What the What-If screen can select instead: 9 AM to midnight, about 76%.
    assert coverage(ALL_DAYS, 9, 24) == pytest.approx(0.76, abs=0.01)


def test_generate_calls_is_seeded_sorted_and_post_screening():
    start = date(2026, 1, 5)  # a Monday
    calls = generate_calls(random.Random(1), start, weeks=52)

    assert calls == generate_calls(random.Random(1), start, weeks=52)
    assert [c.timestamp for c in calls] == sorted(c.timestamp for c in calls)
    assert 2200 < len(calls) < 2700  # ~47/week * 52 = 2,444
    assert all(
        [c.weapon_present, c.violence, c.injury, c.immediate_danger] == [False] * 4
        for c in calls
    )

    sat_sun = sum(c.timestamp.weekday() >= 5 for c in calls) / len(calls)
    assert sat_sun == pytest.approx(0.34, abs=0.04)
    wellbeing = Counter(c.call_type for c in calls)["wellbeing_check"] / len(calls)
    assert wellbeing == pytest.approx(0.30, abs=0.04)


def test_duration_multiplier_clipped_with_mean_near_one():
    rng = random.Random(2)
    draws = [duration_multiplier(rng) for _ in range(20_000)]
    assert all(0.25 <= d <= 4 for d in draws)
    assert sum(draws) / len(draws) == pytest.approx(1, abs=0.05)
