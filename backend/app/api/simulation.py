from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models import Incident, SimulationConfig, SimulationResult
from app.services.simulator import run_comparison, simulate_incidents


router = APIRouter(prefix="/simulation", tags=["What-If Simulator"])


class SimulationRequest(BaseModel):
    config: SimulationConfig
    incidents: list[Incident]


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
