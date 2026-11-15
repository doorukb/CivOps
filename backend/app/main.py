from fastapi import FastAPI
from app.models import Incident, Decision, EvaluationRequest
from app.services.rule_engine import evaluate_incident
from app.api.audit import router as audit_router
from app.api.simulation import router as simulation_router
from fastapi import HTTPException
from pydantic import BaseModel
from app.services.extractor import extract_incident


app = FastAPI(title="CivOps API")
app.include_router(audit_router)
app.include_router(simulation_router)

@app.get("/")
def root():
    return {"message": "CivOps backend is running!"}


@app.post("/calls/evaluate", response_model=Decision)
def evaluate_call(request: EvaluationRequest):
    return evaluate_incident(
        incident=request.incident,
        transcript=request.transcript
    )

class ExtractionRequest(BaseModel):
    transcript: str


@app.post("/calls/extract", response_model=Incident)
def extract_call(request: ExtractionRequest):
    if not request.transcript.strip():
        raise HTTPException(
            status_code=400,
            detail="Transcript cannot be empty"
        )

    try:
        return extract_incident(request.transcript)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI extraction service unavailable"
        )