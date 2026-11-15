import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse
from starlette.websockets import WebSocketClose

from app.api.audit import router as audit_router
from app.api.simulation import router as simulation_router
from app.models import Decision, EvaluationRequest, Incident, TranscriptEvent
from app.services.extractor import extract_incident
from app.services.rule_engine import evaluate_incident
from app.services.call_session import (
    CALL_ENDED,
    CALL_ERROR,
    CALL_STARTED,
    SCENARIOS,
    play_scenario as run_scenario,
    system_event,
)
from app.services.tripwires import scan_transcript

logger = logging.getLogger(__name__)

# The server's event loop; worker threads post to it via run_coroutine_threadsafe.
event_loop: asyncio.AbstractEventLoop | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global event_loop
    event_loop = asyncio.get_running_loop()
    yield
    event_loop = None


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LocalOriginOnly:
    """Refuse browser requests sent from any page that isn't on localhost.

    Without this, any website the operator visits could POST /calls/start
    (no body, so CORS never blocks it) to turn on this machine's microphone,
    and open /ws/transcript (WebSockets ignore CORS) to read the call. It
    also stops DNS rebinding. Requests without an Origin header (curl, the
    mic script, tests) are not from a browser page and pass through.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            origin = dict(scope["headers"]).get(b"origin")
            if origin is not None and (
                urlsplit(origin.decode("latin-1")).hostname not in LOCAL_HOSTS
            ):
                if scope["type"] == "websocket":
                    reject = WebSocketClose(code=1008)
                else:
                    reject = PlainTextResponse("Forbidden origin", 403)
                return await reject(scope, receive, send)
        await self.app(scope, receive, send)


app = FastAPI(title="CivOps API", lifespan=lifespan)
app.add_middleware(LocalOriginOnly)
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
    transcript: str = Field(max_length=20_000)


@app.post("/calls/extract", response_model=Incident)
def extract_call(request: ExtractionRequest):
    if not request.transcript.strip():
        raise HTTPException(
            status_code=400,
            detail="Transcript cannot be empty"
        )

    try:
        return extract_incident(request.transcript)
    except Exception as error:
        # Never log the transcript itself, only the failure.
        logger.error(
            "Extraction failed: %s: %s", type(error).__name__, error
        )
        raise HTTPException(
            status_code=502,
            detail="AI extraction service unavailable"
        )


@app.post("/calls/screen")
def screen_call(request: ExtractionRequest):
    # Keyword tripwires only, no AI call.
    return {"tripwire_flags": scan_transcript(request.transcript)}


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


async def broadcast_event(event: TranscriptEvent) -> int:
    """Send an event to every connected browser; return how many got it."""
    delivered = 0

    for client in tuple(transcript_clients):
        try:
            await client.send_json(event.model_dump())
            delivered += 1
        except Exception:
            transcript_clients.discard(client)

    return delivered


@app.post("/transcript/event")
async def publish_transcript_event(event: TranscriptEvent):
    return {"delivered_to": await broadcast_event(event)}


def post_system_event(text: str):
    """Broadcast a lifecycle marker from a worker thread."""
    if event_loop is None:
        return
    asyncio.run_coroutine_threadsafe(
        broadcast_event(system_event(text)), event_loop
    )


# One session at a time: either the microphone or a scripted call.
session_lock = threading.Lock()
microphone_thread = None
microphone_stop_event = None
script_task: asyncio.Task | None = None


def session_running() -> bool:
    return microphone_thread is not None or (
        script_task is not None and not script_task.done()
    )


def microphone_worker(stop_event):
    global microphone_thread, microphone_stop_event
    marker = CALL_ENDED

    try:
        # Imported lazily so a broken audio stack only affects live calls.
        from scripts.live_microphone import main as run_microphone

        run_microphone(
            stop_event,
            on_ready=lambda: post_system_event(CALL_STARTED),
        )
    except Exception as error:
        print("Microphone session failed:", error)
        marker = CALL_ERROR
    finally:
        # Free the slot first so a Start right after ENDED is accepted.
        with session_lock:
            if microphone_stop_event is stop_event:
                microphone_thread = None
                microphone_stop_event = None

        # run_microphone drains its publisher queue before returning,
        # so this always arrives after the last transcript words.
        post_system_event(marker)


@app.post("/calls/start")
def start_microphone_call():
    global microphone_thread, microphone_stop_event

    with session_lock:
        if session_running():
            return {"status": "already_running"}

        stop_event = threading.Event()

        thread = threading.Thread(
            target=microphone_worker,
            args=(stop_event,),
            daemon=True
        )

        microphone_stop_event = stop_event
        microphone_thread = thread
        thread.start()

    return {"status": "starting"}


@app.post("/calls/end")
def end_microphone_call():
    with session_lock:
        if microphone_stop_event is not None:
            microphone_stop_event.set()
            return {"status": "stopping"}

        if script_task is not None and not script_task.done():
            event_loop.call_soon_threadsafe(script_task.cancel)
            return {"status": "stopping"}

    return {"status": "not_running"}


@app.get("/scenarios")
def list_scenarios():
    return [
        {"id": s.id, "title": s.title, "segments": len(s.lines)}
        for s in SCENARIOS.values()
    ]


@app.post("/scenarios/{scenario_id}/play")
async def play_scenario(
    scenario_id: str,
    speed: float = Query(1.0, gt=0, le=100)
):
    global script_task

    if scenario_id not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown scenario")

    with session_lock:
        if session_running():
            return {"status": "already_running"}

        script_task = asyncio.create_task(
            run_scenario(scenario_id, broadcast_event, speed)
        )

    return {"status": "started"}
