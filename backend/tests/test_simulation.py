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

from app.services.simulator import run_simulation


def test_simulation_capacity():
    config = SimulationConfig(teams=1)

    result = run_simulation(
        config=config,
        call_times=[0, 10, 20],
        durations=[60, 60, 60]
    )

    assert result.total_calls == 3
    assert result.handled_calls == 1
    assert result.missed_busy == 2

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