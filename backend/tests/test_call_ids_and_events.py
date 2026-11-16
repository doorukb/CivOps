"""Call IDs, token-gated event injection and the in-process microphone path (S-02)."""

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.models import TranscriptEvent
from app.services.call_session import play_scenario

EVENT = {"speaker": "caller", "text": "hello", "is_final": True, "t": 0.0}


def collect_until_ended(ws):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["text"] in ("__call_ended__", "__call_error__"):
            return events


def test_caller_can_choose_the_call_id():
    """The page picks the ID before it asks, so it can tell its own events
    from the very first one."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcript") as ws:
            body = client.post(
                "/scenarios/hidden_knife/play?speed=100&call_id=my-call-0001"
            ).json()
            events = collect_until_ended(ws)

    assert body == {"status": "started", "call_id": "my-call-0001"}
    assert {e["call_id"] for e in events} == {"my-call-0001"}


def test_two_calls_in_a_row_never_share_an_id():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcript") as ws:
            first = client.post("/scenarios/hidden_knife/play?speed=100").json()["call_id"]
            first_events = collect_until_ended(ws)
            second = client.post("/scenarios/hidden_knife/play?speed=100").json()["call_id"]
            second_events = collect_until_ended(ws)

    assert first != second
    assert {e["call_id"] for e in first_events} == {first}
    assert {e["call_id"] for e in second_events} == {second}


@pytest.mark.parametrize("bad", ["short", "has space 123", "x" * 65, "semi;colon123"])
def test_malformed_call_id_is_rejected(bad):
    client = TestClient(app)

    assert client.post("/scenarios/hidden_knife/play", params={"call_id": bad}).status_code == 422
    assert client.post("/calls/start", params={"call_id": bad}).status_code == 422


def test_scripted_events_carry_the_call_id_at_the_source():
    events = []

    async def collect(event):
        events.append(event)

    asyncio.run(play_scenario("hidden_knife", collect, speed=100, call_id="abc12345"))

    assert events and all(event.call_id == "abc12345" for event in events)


def test_start_call_passes_the_call_id_to_the_worker(monkeypatch):
    started = []
    monkeypatch.setattr(
        main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    try:
        body = TestClient(app).post("/calls/start").json()
    finally:
        main.microphone_thread = None
        main.microphone_stop_event = None

    assert body["status"] == "starting"
    assert started[0]["args"][1] == body["call_id"]


# --- /transcript/event is off unless a shared token is configured ------------

def test_event_injection_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DESPATCH_EVENT_TOKEN", raising=False)

    response = TestClient(app).post("/transcript/event", json=EVENT)

    assert response.status_code == 403
    assert response.json()["detail"] == "Event injection is disabled"


@pytest.mark.parametrize("headers", [{}, {"X-Despatch-Token": "wrong"}, {"X-Despatch-Token": ""}])
def test_event_injection_needs_the_right_token(monkeypatch, headers):
    monkeypatch.setenv("DESPATCH_EVENT_TOKEN", "s3cret-token")

    response = TestClient(app).post("/transcript/event", json=EVENT, headers=headers)

    assert response.status_code == 403


def test_event_injection_with_the_token_reaches_the_page(monkeypatch):
    monkeypatch.setenv("DESPATCH_EVENT_TOKEN", "s3cret-token")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcript") as ws:
            response = client.post(
                "/transcript/event",
                json={**EVENT, "call_id": "standalone-01"},
                headers={"X-Despatch-Token": "s3cret-token"},
            )
            received = ws.receive_json()

    assert response.json() == {"delivered_to": 1}
    assert (received["text"], received["call_id"]) == ("hello", "standalone-01")


# --- In-process microphone path ----------------------------------------------

def test_microphone_worker_publishes_in_process_in_order(monkeypatch):
    """Events go straight to the broadcaster (no HTTP self-post), each one is
    stamped with the call ID, and the end marker comes last."""
    import sys
    import types

    def fake_run_microphone(stop_event, on_ready, publish):
        on_ready()
        publish(TranscriptEvent(speaker="unknown", text="first", is_final=True, t=0.1))
        publish(TranscriptEvent(speaker="unknown", text="last words", is_final=True, t=0.2))

    monkeypatch.setitem(
        sys.modules, "scripts.live_microphone", types.SimpleNamespace(main=fake_run_microphone)
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcript") as ws:
            worker = threading.Thread(
                target=main.microphone_worker, args=(threading.Event(), "mic-call-01")
            )
            worker.start()
            events = collect_until_ended(ws)
            worker.join(timeout=5)

    assert [e["text"] for e in events] == [
        "__call_started__", "first", "last words", "__call_ended__",
    ]
    assert {e["call_id"] for e in events} == {"mic-call-01"}


def test_posting_from_a_thread_without_a_running_server_is_a_no_op(monkeypatch):
    monkeypatch.setattr(main, "event_loop", None)

    main.post_system_event("__call_ended__", "call-1234")  # must not raise


def test_end_call_without_a_lifespan_cancels_the_script_directly(monkeypatch):
    """/calls/end used to raise AttributeError when the app ran without its
    lifespan (event_loop is None)."""
    cancelled = []
    task = type("Task", (), {"done": lambda self: False, "cancel": lambda self: cancelled.append(1)})()
    monkeypatch.setattr(main, "event_loop", None)
    monkeypatch.setattr(main, "script_task", task)
    monkeypatch.setattr(main, "microphone_stop_event", None)

    assert main.end_microphone_call() == {"status": "stopping"}
    assert cancelled == [1]


def test_dead_client_is_dropped_and_others_still_receive():
    class Dead:
        async def send_json(self, _):
            raise RuntimeError("socket closed")

    received = []

    class Alive:
        async def send_json(self, payload):
            received.append(payload)

    dead, alive = Dead(), Alive()
    main.transcript_clients.update({dead, alive})
    try:
        delivered = asyncio.run(main.broadcast_event(TranscriptEvent(**EVENT)))
    finally:
        main.transcript_clients.discard(alive)

    assert delivered == 1 and received[0]["text"] == "hello"
    assert dead not in main.transcript_clients


def test_microphone_failure_is_logged_without_any_transcript(monkeypatch, caplog):
    import sys
    import types

    def failing(stop_event, on_ready, publish):
        publish(TranscriptEvent(speaker="unknown", text="secret words", is_final=True, t=0.1))
        raise RuntimeError("deepgram down")

    monkeypatch.setitem(
        sys.modules, "scripts.live_microphone", types.SimpleNamespace(main=failing)
    )
    monkeypatch.setattr(main, "event_loop", None)

    main.microphone_worker(threading.Event(), "call-1234")

    assert "RuntimeError: deepgram down" in caplog.text
    assert "secret words" not in caplog.text
