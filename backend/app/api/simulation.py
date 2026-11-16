from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.models import (
    MAX_SIMULATION_INCIDENTS,
    Incident,
    SimulationConfig,
    SimulationResult,
)
from app.rulebook import load_rulebook
from app.services.leap_arrivals import ARRIVAL_MODEL, CALLS_PER_WEEK, coverage
from app.services.simulator import run_comparison, simulate_incidents

router = APIRouter(prefix="/simulation", tags=["What-If Simulator"])


class SimulationRequest(BaseModel):
    config: SimulationConfig
    incidents: list[Incident] = Field(max_length=MAX_SIMULATION_INCIDENTS)

    @field_validator("incidents")
    @classmethod
    def require_aware_timestamps(cls, incidents: list[Incident]) -> list[Incident]:
        """The simulator orders calls by time and subtracts timestamps, so each
        one must exist and carry a UTC offset. Rejecting here gives the caller a
        422 with the offending index instead of a 500 from inside the run."""
        for index, incident in enumerate(incidents):
            timestamp = incident.timestamp
            if timestamp is None:
                raise ValueError(f"incidents[{index}].timestamp is required")
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(
                    f"incidents[{index}].timestamp must include a UTC offset "
                    "(for example 2026-11-16T10:00:00-05:00)"
                )
        return incidents


@router.post("/run", response_model=SimulationResult)
def run_simulation_endpoint(request: SimulationRequest):
    return simulate_incidents(
        incidents=request.incidents,
        config=request.config
    )


class ComparisonRequest(BaseModel):
    baseline: SimulationConfig = Field(default_factory=lambda: baseline_config())
    scenario: SimulationConfig
    replications: int = Field(default=50, ge=1, le=200)
    seed: int = 42
    calls_per_week: float = Field(default=CALLS_PER_WEEK, gt=0, le=500)
    horizon_weeks: int = Field(default=4, ge=1, le=13)
    duration_cv: float = Field(default=0.5, ge=0, le=1.5)


def baseline_config() -> SimulationConfig:
    """Today's schedule, read from the rulebook rather than restated here."""
    rulebook = load_rulebook()
    schedule = rulebook.schedule

    return SimulationConfig(
        start_hour=schedule.start_hour,
        end_hour=schedule.end_hour,
        include_weekends=set(schedule.weekdays) == set(range(7)),
        include_noise_complaints="noise_complaint" in rulebook.eligible_call_types,
    )


def _preset(preset_id: str, label: str, note: str, config: SimulationConfig) -> dict:
    days = range(7) if config.include_weekends else load_rulebook().schedule.weekdays
    return {
        "id": preset_id,
        "label": label,
        "note": note,
        "config": config,
        # Share of arrivals that fall inside the schedule, before team limits.
        "schedule_coverage": coverage(days, config.start_hour, config.end_hour),
    }


@router.get("/baseline")
def simulation_baseline():
    """The reference schedule and the named scenarios the console offers."""
    baseline = baseline_config()

    return {
        "baseline": baseline,
        "calls_per_week": CALLS_PER_WEEK,
        "calibrated_to_leap": ARRIVAL_MODEL.calibrated_to_leap,
        "presets": [
            _preset(
                "extend_to_8pm",
                "Extend weekdays to 8 PM",
                "Today's days, four more hours.",
                baseline.model_copy(update={"end_hour": 20}),
            ),
            _preset(
                "leap_recommended",
                "LEAP recommended: every day, 9 AM to 2 AM",
                "The schedule LEAP's report recommends. 26 means 2 AM the next day.",
                baseline.model_copy(
                    update={"start_hour": 9, "end_hour": 26, "include_weekends": True}
                ),
            ),
        ],
    }


@router.post("/compare")
def compare_simulations(request: ComparisonRequest):
    return run_comparison(**dict(request))
