import asyncio
import hmac
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse
from starlette.websockets import WebSocketClose

from app.api.audit import router as audit_router
from app.api.records import router as records_router
from app.api.simulation import router as simulation_router
from app.models import (
    CALL_ID_PATTERN,
    MAX_TRANSCRIPT_CHARS,
    Decision,
    EvaluationRequest,
    TranscriptEvent,
)
from app.services.call_session import (
    CALL_ENDED,
    CALL_ERROR,
    CALL_STARTED,
    SCENARIOS,
    system_event,
)
from app.services.call_session import (
    play_scenario as run_scenario,
)
from app.services.extractor import ExtractionResult, extract_incident
from app.services.rule_engine import evaluate_incident
from app.services.store import get_store
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


# "testserver" is the Host that Starlette's TestClient sends.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
ALLOWED_HOSTS = LOCAL_HOSTS | {"testserver"}


def _hostname(value: bytes | None) -> str | None:
    """Host name from a Host header ("localhost:8000", "[::1]:8000") or an
    Origin ("http://localhost:5173"), without the port."""
    if not value:
        return None
    text = value.decode("latin-1").strip()
    try:
        return urlsplit(text if "://" in text else f"//{text}").hostname
    except ValueError:
        return None


class LocalRequestsOnly:
    """Serve this machine only. Two independent checks on every HTTP request
    and WebSocket handshake:

    * Origin: refuse requests sent by a page that is not on localhost. Without
      this, any website the operator visits could POST /calls/start (no body,
      so CORS never blocks it) to turn on this machine's microphone, and open
      /ws/transcript (WebSockets ignore CORS) to read the call. Requests with
      no Origin header (curl, tests) are not from a browser page and pass.
    * Host: refuse requests addressed to any name other than localhost. A
      DNS-rebinding page is "same-origin" from the browser's point of view, so
      it may send no Origin at all, but it still has to send its own host name.

    Neither check is authentication: any program on this machine can still
    call the API. Keep the server bound to 127.0.0.1.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope["headers"])
            origin = headers.get(b"origin")

            if _hostname(headers.get(b"host")) not in ALLOWED_HOSTS:
                problem = "Forbidden host"
            elif origin is not None and _hostname(origin) not in LOCAL_HOSTS:
                problem = "Forbidden origin"
            else:
                problem = None

            if problem:
                if scope["type"] == "websocket":
                    reject = WebSocketClose(code=1008)
                else:
                    reject = PlainTextResponse(problem, 403)
                return await reject(scope, receive, send)

        await self.app(scope, receive, send)


app = FastAPI(
    title="Despatch API",
    version="1.0.0",
    summary="Synthetic demonstration of rule-based dispatch decision support.",
    description=(
        "Not a 911 system and not an official Town of Amherst or CRESS tool. "
        "The rulebook is illustrative and all data is synthetic. A language "
        "model extracts facts; plain code decides; a human reviews every "
        "recommendation."
    ),
    lifespan=lifespan,
)
app.add_middleware(LocalRequestsOnly)
app.include_router(audit_router)
app.include_router(simulation_router)
app.include_router(records_router)


@app.get("/")
def root():
    return {
        "message": "Despatch backend is running!",
        "notice": "Synthetic demonstration only. Not a 911 system.",
        "docs": "/docs",
    }


@app.post("/calls/evaluate", response_model=Decision)
def evaluate_call(request: EvaluationRequest):
    return evaluate_incident(
        incident=request.incident,
        transcript=request.transcript
    )


class ExtractionRequest(BaseModel):
    transcript: str = Field(max_length=MAX_TRANSCRIPT_CHARS)


@app.post("/calls/extract", response_model=ExtractionResult)
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
        ) from error


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


def record_event(event: TranscriptEvent) -> None:
    """Write a call's lifecycle and (where allowed) its final transcript lines
    to the call log. The log is best effort: a database problem must never
    interrupt a call."""
    if event.call_id is None:
        return

    try:
        store = get_store()

        if event.speaker == "system":
            if event.text in (CALL_ENDED, CALL_ERROR):
                store.end_call(
                    event.call_id, "ended" if event.text == CALL_ENDED else "error"
                )
        elif event.is_final:
            # The store keeps words only for scripted (fictional) calls.
            store.add_segment(event.call_id, event.t, event.speaker, event.text)
    except Exception as error:
        logger.error("Call log write failed: %s", type(error).__name__)


def open_call_record(call_id: str, source: str) -> None:
    try:
        get_store().start_call(call_id, source)
    except Exception as error:
        logger.error("Call log write failed: %s", type(error).__name__)


async def publish_event(event: TranscriptEvent) -> int:
    """Log, then broadcast. Every event of a session goes through here."""
    record_event(event)
    return await broadcast_event(event)


def event_token() -> str:
    return os.environ.get("DESPATCH_EVENT_TOKEN", "")


@app.post("/transcript/event")
async def publish_transcript_event(
    event: TranscriptEvent,
    x_despatch_token: str | None = Header(default=None),
):
    """Inject a transcript event from outside the process.

    Only for the standalone microphone script. Disabled unless the backend was
    started with DESPATCH_EVENT_TOKEN, and the caller must send the same value in
    X-Despatch-Token. The in-process microphone and the scripted calls never use
    this endpoint.
    """
    expected = event_token()

    if not expected:
        raise HTTPException(status_code=403, detail="Event injection is disabled")

    if not hmac.compare_digest((x_despatch_token or "").encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid event token")

    return {"delivered_to": await broadcast_event(event)}


def post_event(event: TranscriptEvent, timeout: float = 2.0) -> None:
    """Broadcast from a worker thread and wait until it has been sent, so
    events and the end marker reach the page in the order they were posted."""
    loop = event_loop

    if loop is None:
        return  # server is shutting down, or the app runs without a lifespan

    future = asyncio.run_coroutine_threadsafe(publish_event(event), loop)

    try:
        future.result(timeout=timeout)
    except Exception as error:
        logger.warning("Could not deliver a transcript event: %s", type(error).__name__)


def post_system_event(text: str, call_id: str | None = None) -> None:
    """Broadcast a lifecycle marker from a worker thread."""
    post_event(system_event(text, call_id))


# One session at a time: either the microphone or a scripted call.
session_lock = threading.Lock()
microphone_thread = None
microphone_stop_event = None
script_task: asyncio.Task | None = None

CallId = Query(
    default=None,
    pattern=CALL_ID_PATTERN,
    description=(
        "Optional ID for this call, chosen by the caller so it knows which "
        "events are its own before the first one arrives. Generated if omitted."
    ),
)


def new_call_id() -> str:
    return uuid.uuid4().hex


def session_running() -> bool:
    return microphone_thread is not None or (
        script_task is not None and not script_task.done()
    )


def microphone_worker(stop_event, call_id: str | None = None):
    global microphone_thread, microphone_stop_event
    marker = CALL_ENDED

    try:
        # Imported lazily so a broken audio stack only affects live calls.
        from scripts.live_microphone import main as run_microphone

        run_microphone(
            stop_event,
            on_ready=lambda: post_system_event(CALL_STARTED, call_id),
            # In-process: events never leave this process or touch HTTP.
            publish=lambda event: post_event(
                event.model_copy(update={"call_id": call_id})
            ),
        )
    except Exception as error:
        # Log what failed, never what was said.
        logger.error("Microphone session failed: %s: %s", type(error).__name__, error)
        marker = CALL_ERROR
    finally:
        # Free the slot first so a Start right after ENDED is accepted.
        with session_lock:
            if microphone_stop_event is stop_event:
                microphone_thread = None
                microphone_stop_event = None

        # run_microphone drains its publisher queue before returning,
        # so this always arrives after the last transcript words.
        post_system_event(marker, call_id)


@app.post("/calls/start")
def start_microphone_call(call_id: str | None = CallId):
    global microphone_thread, microphone_stop_event

    with session_lock:
        if session_running():
            return {"status": "already_running"}

        call_id = call_id or new_call_id()
        open_call_record(call_id, "microphone")
        stop_event = threading.Event()

        thread = threading.Thread(
            target=microphone_worker,
            args=(stop_event, call_id),
            daemon=True
        )

        microphone_stop_event = stop_event
        microphone_thread = thread
        thread.start()

    return {"status": "starting", "call_id": call_id}


@app.post("/calls/end")
def end_microphone_call():
    with session_lock:
        if microphone_stop_event is not None:
            microphone_stop_event.set()
            return {"status": "stopping"}

        if script_task is not None and not script_task.done():
            loop = event_loop
            if loop is not None:
                loop.call_soon_threadsafe(script_task.cancel)
            else:  # no lifespan (e.g. a bare ASGI harness): cancel directly
                script_task.cancel()
            return {"status": "stopping"}

    return {"status": "not_running"}


@app.get("/scenarios")
def list_scenarios():
    return [
        {"id": s.id, "title": s.title, "summary": s.summary, "segments": len(s.lines)}
        for s in SCENARIOS.values()
    ]


@app.post("/scenarios/{scenario_id}/play")
async def play_scenario(
    scenario_id: str,
    speed: float = Query(1.0, gt=0, le=100),
    call_id: str | None = CallId,
):
    global script_task

    if scenario_id not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown scenario")

    with session_lock:
        if session_running():
            return {"status": "already_running"}

        call_id = call_id or new_call_id()
        open_call_record(call_id, f"script:{scenario_id}")
        script_task = asyncio.create_task(
            run_scenario(scenario_id, publish_event, speed, call_id)
        )

    return {"status": "started", "call_id": call_id}
