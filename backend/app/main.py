from fastapi import FastAPI
from app.models import Incident, Decision, EvaluationRequest
from app.services.rule_engine import evaluate_incident

app = FastAPI(title="CivOps API")


@app.get("/")
def root():
    return {"message": "CivOps backend is running!"}


@app.post("/calls/evaluate", response_model=Decision)
def evaluate_call(request: EvaluationRequest):
    return evaluate_incident(
        incident=request.incident,
        transcript=request.transcript
    )