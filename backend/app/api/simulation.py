from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.models import (
    MAX_SIMULATION_INCIDENTS,
    Incident,
    SimulationConfig,
    SimulationResult,
)
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
    baseline: SimulationConfig = Field(default_factory=SimulationConfig)
    scenario: SimulationConfig
    replications: int = Field(default=50, ge=1, le=200)
    seed: int = 42
    calls_per_week: float = Field(default=47, gt=0, le=500)
    horizon_weeks: int = Field(default=4, ge=1, le=13)
    duration_cv: float = Field(default=0.5, ge=0, le=1.5)


@router.post("/compare")
def compare_simulations(request: ComparisonRequest):
    return run_comparison(**dict(request))
