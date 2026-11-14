from fastapi import APIRouter

from app.models import Incident, SimulationConfig, SimulationResult
from app.services.simulator import simulate_incidents
from pydantic import BaseModel


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