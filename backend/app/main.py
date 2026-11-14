from fastapi import FastAPI
from app.models import Incident

app = FastAPI(title="CivOps API")


@app.get("/")
def root():
    return {"message": "CivOps backend is running!"}


@app.post("/calls/evaluate")
def evaluate_call(incident: Incident):
    return {
        "message": "Incident received successfully",
        "incident": incident.model_dump()
    }