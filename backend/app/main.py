from fastapi import FastAPI
from app.models import Incident, Decision, EvaluationRequest
from app.services.rule_engine import evaluate_incident
from app.api.audit import router as audit_router
from app.api.simulation import router as simulation_router
from fastapi import HTTPException
from pydantic import BaseModel
from app.services.extractor import extract_incident
from fastapi import WebSocket, WebSocketDisconnect
from app.models import TranscriptEvent
import threading

from scripts.live_microphone import main as run_microphone

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

# Browsers currently watching the live transcript
transcript_clients: set[WebSocket] = set()


@app.websocket("/ws/transcript")
async def transcript_websocket(websocket: WebSocket):
    await websocket.accept()
    transcript_clients.add(websocket)

    try:
        while True:
            # Keep the connection alive until the browser disconnects
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    finally:
        transcript_clients.discard(websocket)


@app.post("/transcript/event")
async def publish_transcript_event(event: TranscriptEvent):
    disconnected = []

    for client in tuple(transcript_clients):
        try:
            await client.send_json(event.model_dump())
        except Exception:
            disconnected.append(client)

    for client in disconnected:
        transcript_clients.discard(client)

    return {
        "delivered_to": len(transcript_clients) - len(disconnected)
        if not disconnected else len(
            [client for client in transcript_clients]
        )
    }

# Local microphone session management
microphone_lock = threading.Lock()
microphone_thread = None
microphone_stop_event = None


def microphone_worker(stop_event):
    global microphone_thread, microphone_stop_event

    try:
        run_microphone(stop_event)
    except Exception as error:
        print("Microphone session failed:", error)
    finally:
        with microphone_lock:
            if microphone_stop_event is stop_event:
                microphone_thread = None
                microphone_stop_event = None


@app.post("/calls/start")
def start_microphone_call():
    global microphone_thread, microphone_stop_event

    with microphone_lock:
        if microphone_thread is not None:
            return {
                "status": "already_running"
            }

        stop_event = threading.Event()

        thread = threading.Thread(
            target=microphone_worker,
            args=(stop_event,),
            daemon=True
        )

        microphone_stop_event = stop_event
        microphone_thread = thread
        thread.start()

    return {
        "status": "starting"
    }


@app.post("/calls/end")
def end_microphone_call():
    with microphone_lock:
        if microphone_stop_event is None:
            return {
                "status": "not_running"
            }

        microphone_stop_event.set()

    return {
        "status": "stopping"
    }