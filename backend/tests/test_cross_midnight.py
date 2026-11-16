"""Schedules that run past midnight (G-02).

LEAP's recommended schedule is every day, 9 AM to 2 AM. end_hour 26 means
2 AM the next day; `weekdays` are the days a shift starts.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import SAFETY_FIELDS, Destination, Incident, SimulationConfig
from app.rulebook import load_rulebook
from app.services.leap_arrivals import HOUR_WEIGHTS, coverage
from app.services.rule_engine import evaluate_incident, is_on_duty
from app.services.simulator import run_comparison, simulate_incidents

TZ = load_rulebook().schedule.tzinfo
LEAP = {"start_hour": 9, "end_hour": 26}
EVERY_DAY = tuple(range(7))


def schedule(weekdays=EVERY_DAY, **hours):
    return load_rulebook().with_changes(schedule={"weekdays": weekdays, **hours}).schedule


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """November 2026: the 16th is a Monday, the 22nd a Sunday."""
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def call(when: datetime) -> Incident:
    return Incident(
        call_type="wellbeing_check", timestamp=when, **dict.fromkeys(SAFETY_FIELDS, False)
    )


@pytest.mark.parametrize(
    "hour, minute, on_duty",
    [
        (8, 59, False),
        (9, 0, True),
        (23, 59, True),
        (0, 0, True),    # past midnight, still the shift that started yesterday
        (1, 59, True),
        (2, 0, False),   # the shift ended
        (5, 0, False),
    ],
)
def test_boundaries_of_a_shift_that_ends_at_2am(hour, minute, on_duty):
    assert is_on_duty(schedule(**LEAP), at(17, hour, minute)) is on_duty


def test_small_hours_belong_to_the_day_the_shift_started():
    weekdays_only = schedule(weekdays=(0, 1, 2, 3, 4), **LEAP)

    # Friday's shift runs into Saturday 1 AM.
    assert is_on_duty(weekdays_only, at(21, 1)) is True
    # Saturday has no shift, so Sunday 1 AM is off duty...
    assert is_on_duty(weekdays_only, at(22, 1)) is False
    # ...and so is Monday 1 AM (Sunday has no shift), until Monday 9 AM.
    assert is_on_duty(weekdays_only, at(16, 1)) is False
    assert is_on_duty(weekdays_only, at(16, 9)) is True


def test_sunday_night_runs_into_monday_morning():
    sunday_only = schedule(weekdays=(6,), **LEAP)

    assert is_on_duty(sunday_only, at(22, 23)) is True   # Sunday 11 PM
    assert is_on_duty(sunday_only, at(23, 1)) is True    # Monday 1 AM (week wraps)
    assert is_on_duty(sunday_only, at(23, 10)) is False  # Monday 10 AM: no Monday shift


def test_rule_engine_routes_a_1am_call_to_cress_under_the_leap_schedule():
    leap = load_rulebook().with_changes(schedule={"weekdays": EVERY_DAY, **LEAP})

    assert evaluate_incident(call(at(17, 1, 59)), leap).destination == Destination.CRESS
    assert evaluate_incident(call(at(17, 2, 0)), leap).destination == Destination.CRESS_FOLLOWUP
    # The shipped schedule (weekdays 8 to 16) is unchanged.
    assert evaluate_incident(call(at(17, 1, 59))).destination == Destination.CRESS_FOLLOWUP


def test_schedules_that_stay_inside_one_day_behave_as_before():
    day_shift = schedule(weekdays=(0, 1, 2, 3, 4), start_hour=8, end_hour=16)

    assert [is_on_duty(day_shift, at(16, h)) for h in (7, 8, 15, 16)] == [False, True, True, False]
    assert is_on_duty(schedule(start_hour=0, end_hour=24), at(18, 0)) is True


@pytest.mark.parametrize(
    "start, end, problem",
    [
        (9, 27, "less than or equal to 26"),
        (0, 26, "must end before the next one starts"),
        (1, 26, "must end before the next one starts"),
        (20, 8, "end_hour must be greater than start_hour"),
    ],
)
def test_impossible_shifts_are_rejected_everywhere(start, end, problem):
    with pytest.raises(ValidationError, match=problem):
        SimulationConfig(start_hour=start, end_hour=end)
    with pytest.raises(ValidationError, match=problem):
        schedule(start_hour=start, end_hour=end)


def test_two_am_start_with_two_am_end_is_the_longest_legal_shift():
    assert SimulationConfig(start_hour=2, end_hour=26).end_hour == 26


# --- coverage ----------------------------------------------------------------

def test_coverage_of_the_leap_schedule_is_about_87_percent():
    by_hand = sum(HOUR_WEIGHTS[9:24]) + HOUR_WEIGHTS[0] + HOUR_WEIGHTS[1]

    assert coverage(EVERY_DAY, 9, 26) == pytest.approx(by_hand)
    assert coverage(EVERY_DAY, 9, 26) == pytest.approx(0.87, abs=0.01)
    assert coverage(EVERY_DAY, 9, 24) == pytest.approx(0.76, abs=0.01)  # the old ceiling


def test_coverage_puts_the_small_hours_on_the_following_weekday():
    # A Friday-only shift's 0-2 AM hours are Saturday's, the busiest day.
    friday = coverage((4,), 9, 26)
    monday = coverage((0,), 9, 26)

    assert friday > monday
    assert sum(coverage((d,), 9, 26) for d in range(7)) == pytest.approx(coverage(EVERY_DAY, 9, 26))


# --- simulator ---------------------------------------------------------------

def test_unlimited_teams_on_the_leap_schedule_handle_about_87_percent():
    config = SimulationConfig(teams=20, include_weekends=True, **LEAP)

    result = run_comparison(config, config, replications=50)

    assert result["baseline"]["share_handled"]["mean"] == pytest.approx(0.87, abs=0.02)
    assert result["baseline"]["missed_busy"]["mean"] == 0


def test_capacity_counts_every_on_duty_hour_in_the_horizon():
    """One team, every day 9 AM to 2 AM, one week = 7 x 17 on-duty hours."""
    config = SimulationConfig(teams=1, average_duration_minutes=60, include_weekends=True, **LEAP)
    monday = date(2026, 11, 16)
    one_call = [call(at(16, 10))]

    result = simulate_incidents(one_call, config, monday, monday + timedelta(weeks=1))

    assert result.handled_calls == 1
    assert result.utilization == pytest.approx(60 / (7 * 17 * 60))


def test_busy_time_is_capped_at_the_2am_shift_end():
    """A 60-minute call that starts at 1:30 AM uses 30 on-duty minutes."""
    config = SimulationConfig(teams=1, average_duration_minutes=60, include_weekends=True, **LEAP)
    monday = date(2026, 11, 16)

    late = simulate_incidents([call(at(17, 1, 30))], config, monday, monday + timedelta(weeks=1))
    evening = simulate_incidents([call(at(17, 23, 30))], config, monday, monday + timedelta(weeks=1))

    assert late.utilization == pytest.approx(30 / (7 * 17 * 60))
    assert evening.utilization == pytest.approx(60 / (7 * 17 * 60))  # runs through midnight


def test_a_call_after_2am_is_missed_off_duty():
    config = SimulationConfig(teams=1, include_weekends=True, **LEAP)

    result = simulate_incidents([call(at(17, 2, 5))], config)

    assert (result.handled_calls, result.missed_off_duty) == (0, 1)


def test_compare_endpoint_accepts_the_leap_schedule_and_rejects_27():
    client = TestClient(app)
    leap = {"start_hour": 9, "end_hour": 26, "include_weekends": True}

    ok = client.post("/simulation/compare", json={"scenario": leap, "replications": 3})
    assert ok.status_code == 200
    assert ok.json()["scenario"]["share_handled"]["mean"] > ok.json()["baseline"]["share_handled"]["mean"]

    bad = client.post("/simulation/compare", json={"scenario": {**leap, "end_hour": 27}})
    assert bad.status_code == 422
