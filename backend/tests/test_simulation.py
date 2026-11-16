import pytest
from pydantic import ValidationError

from app.models import SimulationConfig


def test_default_simulation_config():
    config = SimulationConfig()

    assert config.start_hour == 8
    assert config.end_hour == 16
    assert config.teams == 3
    assert config.include_weekends is False


def test_invalid_team_count():
    with pytest.raises(ValidationError):
        SimulationConfig(teams=0)

from app.services.simulator import build_scenario_rulebook
from app.services.rule_engine import load_rulebook


def test_scenario_rulebook():
    config = SimulationConfig(
        start_hour=8,
        end_hour=20,
        include_weekends=True
    )

    scenario = build_scenario_rulebook(config)
    baseline = load_rulebook()

    assert scenario["schedule"]["end_hour"] == 20
    assert scenario["schedule"]["weekdays"] == list(range(7))

    # The original policy must remain unchanged
    assert baseline["schedule"]["end_hour"] == 16
    assert baseline["schedule"]["weekdays"] == [0, 1, 2, 3, 4]

from app.models import Incident
from app.services.simulator import simulate_incidents


def test_integrated_simulation():
    incidents = [
        Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T10:00:00-05:00"
        ),
        Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T10:10:00-05:00"
        ),
        Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T19:00:00-05:00"
        )
    ]

    config = SimulationConfig(
        teams=1,
        average_duration_minutes=60
    )

    result = simulate_incidents(incidents, config)

    assert result.total_calls == 3
    assert result.eligible_calls == 3
    assert result.handled_calls == 1
    assert result.missed_busy == 1
    assert result.missed_off_duty == 1

def test_simultaneous_arrivals():
    incidents = [
        Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T10:00:00-05:00"
        )
        for _ in range(3)
    ]

    config = SimulationConfig(
        teams=1,
        average_duration_minutes=60
    )

    result = simulate_incidents(incidents, config)

    assert result.total_calls == 3
    assert result.handled_calls == 1
    assert result.missed_busy == 2

import pytest


def test_utilization():
    incidents = [
        Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T10:00:00-05:00"
        ),
        Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T12:00:00-05:00"
        )
    ]

    config = SimulationConfig(
        teams=1,
        average_duration_minutes=60
    )

    result = simulate_incidents(incidents, config)

    # Two hours busy / eight hours scheduled
    assert result.handled_calls == 2
    assert result.utilization == pytest.approx(0.25)

def test_invalid_schedule():
    with pytest.raises(ValidationError):
        SimulationConfig(
            start_hour=20,
            end_hour=8
        )

def test_equal_start_end_hours():
    with pytest.raises(ValidationError):
        SimulationConfig(
            start_hour=8,
            end_hour=8
        )

from datetime import date, timedelta

from app.services.simulator import run_comparison


def _call(call_type, timestamp):
    return Incident(
        call_type=call_type,
        weapon_present=False,
        violence=False,
        injury=False,
        immediate_danger=False,
        timestamp=timestamp
    )


def test_noise_complaints_only_eligible_when_requested():
    off = build_scenario_rulebook(SimulationConfig())
    on = build_scenario_rulebook(SimulationConfig(include_noise_complaints=True))

    assert "noise_complaint" not in off["eligible_call_types"]
    assert on["eligible_call_types"][-1] == "noise_complaint"
    assert "noise_complaint" not in load_rulebook()["eligible_call_types"]


def test_horizon_fixes_utilization_denominator():
    incidents = [_call("wellbeing_check", "2026-11-16T10:00:00-05:00")]
    config = SimulationConfig(teams=1, average_duration_minutes=60)

    # One call and one day: 60 busy minutes of 480 scheduled
    assert simulate_incidents(incidents, config).utilization == pytest.approx(60 / 480)

    # Mon 16th to Mon 23rd, end exclusive: 5 scheduled days
    result = simulate_incidents(
        incidents, config, date(2026, 11, 16), date(2026, 11, 23)
    )
    assert result.utilization == pytest.approx(60 / (5 * 480))


def test_multipliers_sort_with_their_calls():
    # Listed out of order: the 10:00 call is 3x as long, so it blocks 10:30.
    incidents = [
        _call("wellbeing_check", "2026-11-16T10:30:00-05:00"),
        _call("wellbeing_check", "2026-11-16T10:00:00-05:00"),
    ]
    config = SimulationConfig(teams=1, average_duration_minutes=60)

    long_first = simulate_incidents(incidents, config, duration_multipliers=[0.1, 3.0])
    short_first = simulate_incidents(incidents, config, duration_multipliers=[3.0, 0.1])

    assert (long_first.handled_calls, long_first.missed_busy) == (1, 1)
    assert (short_first.handled_calls, short_first.missed_busy) == (2, 0)

    with pytest.raises(ValueError):
        simulate_incidents(incidents, config, duration_multipliers=[1.0])


def test_run_comparison():
    baseline = SimulationConfig()
    scenario = SimulationConfig(start_hour=8, end_hour=20)

    result = run_comparison(baseline, scenario, replications=20)
    assert result == run_comparison(baseline, scenario, replications=20)

    # Roughly 47/week * 75% eligible * 22% / 36% coverage, per the assumptions
    assert result["baseline"]["calls_per_week"]["mean"] == pytest.approx(7.7, abs=1.5)
    assert result["scenario"]["calls_per_week"]["mean"] == pytest.approx(12.7, abs=2)

    stats = result["difference"]["calls_per_week"]
    assert stats["p10"] <= stats["mean"] <= stats["p90"]
    assert stats["p10"] > 0  # paired on the same calls: longer hours never lose any
    assert len(result["assumptions"]) >= 5


def test_run_comparison_one_team_long_calls_misses_busy():
    tight = SimulationConfig(teams=1, average_duration_minutes=240)
    result = run_comparison(tight, tight, replications=20)

    assert result["baseline"]["missed_busy"]["mean"] > 3


def test_identical_configs_give_zero_paired_difference():
    config = SimulationConfig(teams=2, average_duration_minutes=120)
    result = run_comparison(config, config, replications=10)

    for band in result["difference"].values():
        assert band == {"mean": 0, "p10": 0, "p90": 0}


def test_both_scenarios_see_the_same_calls(monkeypatch):
    import app.services.simulator as simulator

    seen = []
    real = simulator.simulate_incidents

    def spy(calls, config, *args):
        seen.append((calls, args[2]))
        return real(calls, config, *args)

    monkeypatch.setattr(simulator, "simulate_incidents", spy)
    run_comparison(SimulationConfig(), SimulationConfig(end_hour=20), replications=5)

    assert len(seen) == 10
    for baseline, scenario in zip(seen[::2], seen[1::2]):
        assert baseline == scenario  # same calls, same duration multipliers


# 20 teams never run out, so share handled is just schedule coverage:
# the validation the brief promised (22%, 36%, 55%).
@pytest.mark.parametrize(
    "config, expected",
    [
        (SimulationConfig(teams=20), 0.22),
        (SimulationConfig(teams=20, end_hour=20), 0.36),
        (SimulationConfig(teams=20, end_hour=20, include_weekends=True), 0.55),
    ],
)
def test_twenty_teams_reproduce_brief_coverage(config, expected):
    result = run_comparison(config, config, replications=50)
    assert result["baseline"]["share_handled"]["mean"] == pytest.approx(expected, abs=0.02)
    assert result["baseline"]["missed_busy"]["mean"] == 0


def _replications(n=20):
    from app.services.leap_arrivals import duration_multiplier, generate_calls
    import random

    start = date(2026, 1, 5)
    for seed in range(n):
        rng = random.Random(seed)
        calls = generate_calls(rng, start, 4)
        yield calls, start, start + timedelta(weeks=4), [duration_multiplier(rng) for _ in calls]


@pytest.mark.parametrize(
    "config",
    [
        SimulationConfig(),
        SimulationConfig(teams=1, average_duration_minutes=240),
        SimulationConfig(teams=2, end_hour=24, include_weekends=True, include_noise_complaints=True),
    ],
)
def test_outcomes_partition_eligible_and_utilization_is_a_share(config):
    for calls, start, end, mult in _replications(5):
        r = simulate_incidents(calls, config, start, end, mult)
        assert r.handled_calls + r.missed_off_duty + r.missed_busy == r.eligible_calls
        assert 0 <= r.utilization <= 1


@pytest.mark.parametrize(
    "wider",
    [
        SimulationConfig(end_hour=20),
        SimulationConfig(end_hour=20, include_weekends=True),
        SimulationConfig(include_noise_complaints=True),
    ],
)
def test_longer_hours_or_noise_never_reduce_handled(wider):
    # ponytail: holds for the default 3 teams x 60 min; with 1 team and long
    # calls an extra accepted call can block several later ones (loss system).
    for calls, start, end, mult in _replications():
        base = simulate_incidents(calls, SimulationConfig(), start, end, mult)
        more = simulate_incidents(calls, wider, start, end, mult)
        assert more.handled_calls >= base.handled_calls


from fastapi.testclient import TestClient

from app.main import app

compare_client = TestClient(app)


def test_compare_endpoint_defaults_baseline_and_returns_summary():
    response = compare_client.post("/simulation/compare", json={
        "scenario": {"start_hour": 8, "end_hour": 20, "teams": 3},
        "replications": 5,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["replications"] == 5
    assert body["horizon_weeks"] == 4
    assert set(body) >= {"baseline", "scenario", "difference", "assumptions"}
    # Longer hours should not reduce calls handled
    assert body["difference"]["calls_per_week"]["mean"] > 0


def test_compare_endpoint_validates_input():
    ok = {"scenario": {}}
    for bad in (
        {"scenario": {"start_hour": 20, "end_hour": 6}},  # overnight
        {**ok, "replications": 0}, {**ok, "replications": 201},
        {**ok, "calls_per_week": 0}, {**ok, "calls_per_week": 501},
        {**ok, "horizon_weeks": 0}, {**ok, "horizon_weeks": 14},
        {**ok, "duration_cv": -0.1}, {**ok, "duration_cv": 1.6},
    ):
        assert compare_client.post(
            "/simulation/compare", json=bad
        ).status_code == 422, bad
    assert compare_client.post("/simulation/compare", json={}).status_code == 422
