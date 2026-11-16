import subprocess
import sys
import time

from fastapi.testclient import TestClient

import app.main as main
from app.main import app


def collect_until_ended(ws):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["text"] in ("__call_ended__", "__call_error__"):
            return events


def test_importing_app_does_not_load_audio_stack():
    code = (
        "import sys, app.main; "
        "assert 'sounddevice' not in sys.modules; "
        "assert 'scripts.live_microphone' not in sys.modules"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_list_scenarios():
    ids = {s["id"] for s in TestClient(app).get("/scenarios").json()}
    assert {"routine_wellbeing", "hidden_knife", "incomplete_screening"} <= ids


def test_unknown_scenario_is_404():
    assert TestClient(app).post("/scenarios/nope/play").status_code == 404


def test_scripted_call_emits_started_speech_ended():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcript") as ws:
            response = client.post("/scenarios/hidden_knife/play?speed=100")
            body = response.json()
            assert body["status"] == "started" and len(body["call_id"]) == 32
            events = collect_until_ended(ws)

    # Every event of the call, markers included, carries the same call ID.
    assert {e["call_id"] for e in events} == {body["call_id"]}

    assert events[0]["text"] == "__call_started__"
    assert events[-1]["text"] == "__call_ended__"
    speech = [e for e in events if e["speaker"] != "system" and e["is_final"]]
    assert [(e["speaker"], e["text"]) for e in speech] == list(
        main.SCENARIOS["hidden_knife"].lines
    )
    assert any("knife" in e["text"] for e in speech)


def test_one_session_at_a_time_and_end_cancels_script():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcript") as ws:
            client.post("/scenarios/routine_wellbeing/play?speed=0.5")
            assert client.post(
                "/scenarios/hidden_knife/play"
            ).json() == {"status": "already_running"}
            assert client.post("/calls/start").json() == {
                "status": "already_running"
            }

            assert client.post("/calls/end").json() == {"status": "stopping"}
            events = collect_until_ended(ws)
            assert events[-1]["text"] == "__call_ended__"

        time.sleep(0.1)
        assert client.post("/calls/end").json() == {"status": "not_running"}


def test_microphone_worker_failure_sends_error_marker(monkeypatch):
    posted = []
    monkeypatch.setattr(main, "post_system_event", lambda *args: posted.append(args))
    # Importing the real audio script fails or is replaced here; either way,
    # an exception must produce ERROR, never ENDED.
    monkeypatch.setitem(sys.modules, "scripts.live_microphone", None)

    main.microphone_worker(object(), "call-1234")

    assert posted == [("__call_error__", "call-1234")]


def test_screen_endpoint_flags_without_ai():
    client = TestClient(app)
    flagged = client.post(
        "/calls/screen", json={"transcript": "he has a knife"}
    ).json()
    assert "weapon" in flagged["tripwire_flags"]
    clean = client.post("/calls/screen", json={"transcript": "nice day"}).json()
    assert clean == {"tripwire_flags": {}}


def test_extract_rejects_oversized_transcript():
    response = TestClient(app).post(
        "/calls/extract", json={"transcript": "a" * 20_001}
    )
    assert response.status_code == 422


def test_extract_failure_logs_type_not_transcript(monkeypatch, caplog):
    def boom(_):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(main, "extract_incident", boom)
    response = TestClient(app).post(
        "/calls/extract", json={"transcript": "secret words"}
    )

    assert response.status_code == 502
    assert "RuntimeError: upstream down" in caplog.text
    assert "secret words" not in caplog.text
