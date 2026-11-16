"""SQLite call log: calls, transcript segments, decisions, dispatcher reviews (G-04)."""

import csv
import io
import sqlite3
import threading
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.models import SAFETY_FIELDS, Incident
from app.services.rule_engine import evaluate_incident
from app.services.store import SCHEMA_VERSION, Store, get_store

client = TestClient(app)

CLEAN = {
    "call_type": "wellbeing_check",
    **dict.fromkeys(SAFETY_FIELDS, False),
    "timestamp": "2026-11-16T14:00:00-05:00",
}


def collect_until_ended(ws):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["text"] in ("__call_ended__", "__call_error__"):
            return events


def review(**overrides):
    body = {"incident": CLEAN, "action": "confirmed", **overrides}
    return client.post("/reviews", json=body)


# --- reviews -----------------------------------------------------------------

def test_confirm_is_stored_with_the_rule_that_produced_it():
    response = review()

    assert response.status_code == 201
    record = response.json()
    assert record["action"] == "confirmed"
    assert record["rule_id"] == "CRESS-001"
    assert record["recommended_destination"] == record["chosen_destination"] == "cress"
    assert record["call_source"] == "manual"
    assert record["rulebook_version"]
    assert record["simulated_time"] == "2026-11-16T14:00:00-05:00"


def test_override_records_what_the_dispatcher_chose_and_why():
    response = review(
        action="overridden",
        chosen_destination="police",
        reason="Caller called back: the neighbor is now shouting threats.",
    )

    assert response.status_code == 201
    record = response.json()
    assert (record["recommended_destination"], record["chosen_destination"]) == ("cress", "police")
    assert record["reason"].startswith("Caller called back")


@pytest.mark.parametrize(
    "overrides, problem",
    [
        ({"action": "overridden", "reason": "because"}, "which destination"),
        ({"action": "overridden", "chosen_destination": "police"}, "give a reason"),
        ({"action": "overridden", "chosen_destination": "police", "reason": "  "}, "give a reason"),
        ({"action": "overridden", "chosen_destination": "cress", "reason": "same"}, "other than"),
        ({"action": "confirmed", "chosen_destination": "police"}, "use an override"),
        ({"action": "shrugged"}, "confirmed"),
        ({"action": "overridden", "chosen_destination": "moon", "reason": "why"}, "chosen_destination"),
    ],
)
def test_invalid_reviews_are_rejected_and_nothing_is_stored(overrides, problem):
    response = review(**overrides)

    assert response.status_code == 422
    assert problem in response.text
    assert client.get("/reviews").json() == []


def test_server_recomputes_the_recommendation():
    """The client sends facts, not a decision, so it cannot log a
    recommendation the rulebook did not make."""
    record = review(
        incident={**CLEAN, "weapon_present": True},
        action="overridden",
        chosen_destination="police",
        reason="Weapon reported.",
    ).json()

    assert record["rule_id"] == "SAFETY-ESCALATION"
    assert record["recommended_destination"] == "human_review"


def test_tripwire_is_applied_when_a_review_is_recorded():
    record = review(transcript="He has a knife.").json()

    assert record["rule_id"] == "TRANSCRIPT-TRIPWIRE"
    assert record["recommended_destination"] == "human_review"


def test_provisional_recommendation_cannot_be_confirmed():
    """One-way autonomy, enforced by the server: a person must confirm the
    model-proposed 'no' answers first."""
    model_only = {**CLEAN, "provenance": dict.fromkeys(SAFETY_FIELDS, "model")}

    refused = review(incident=model_only)
    assert refused.status_code == 409
    assert refused.json()["detail"]["needs_confirmation"] == list(SAFETY_FIELDS)
    assert client.get("/reviews").json() == []

    confirmed = {**CLEAN, "provenance": dict.fromkeys(SAFETY_FIELDS, "human")}
    assert review(incident=confirmed).status_code == 201


def test_provisional_recommendation_can_still_be_overridden():
    model_only = {**CLEAN, "provenance": dict.fromkeys(SAFETY_FIELDS, "model")}

    response = review(
        incident=model_only, action="overridden",
        chosen_destination="human_review", reason="Not comfortable with this one.",
    )

    assert response.status_code == 201


def test_reviews_are_listed_newest_first_with_a_limit():
    for index in range(3):
        review(action="overridden", chosen_destination="police", reason=f"reason {index}")

    listed = client.get("/reviews?limit=2").json()

    assert [r["reason"] for r in listed] == ["reason 2", "reason 1"]
    assert client.get("/reviews?limit=0").status_code == 422


def test_csv_export_is_oldest_first_and_neutralises_formulas():
    review(action="overridden", chosen_destination="police", reason='=HYPERLINK("http://x","click")')
    review()

    response = client.get("/reviews.csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert [r["action"] for r in rows] == ["overridden", "confirmed"]
    assert rows[0]["reason"].startswith("'=")  # a spreadsheet will not run it
    assert rows[0]["chosen_destination"] == "police"


# --- calls and transcripts ---------------------------------------------------

def play(client, scenario="hidden_knife"):
    with client.websocket_connect("/ws/transcript") as ws:
        call_id = client.post(f"/scenarios/{scenario}/play?speed=100").json()["call_id"]
        collect_until_ended(ws)
    return call_id


def test_scripted_call_is_logged_with_its_transcript():
    with TestClient(app) as live:
        call_id = play(live)
        call = live.get(f"/calls/{call_id}").json()

    assert call["source"] == "script:hidden_knife"
    assert call["outcome"] == "ended" and call["ended_at"]
    assert call["transcript_stored"] is True
    # Only final lines are stored, in order.
    assert [(s["speaker"], s["text"]) for s in call["segments"]] == list(
        main.SCENARIOS["hidden_knife"].lines
    )


def test_review_attaches_to_its_call():
    with TestClient(app) as live:
        call_id = play(live)
        live.post("/reviews", json={
            "call_id": call_id, "incident": CLEAN, "action": "confirmed",
            "transcript": "Caller: I just heard a man yell that he has a knife!",
        })
        call = live.get(f"/calls/{call_id}").json()
        listed = live.get("/calls").json()

    assert call["reviews"][0]["rule_id"] == "TRANSCRIPT-TRIPWIRE"
    assert call["decisions"][0]["incident"]["call_type"] == "wellbeing_check"
    assert listed[0]["call_id"] == call_id
    assert (listed[0]["segments"], listed[0]["reviews"]) == (5, 1)


def test_unknown_call_is_404():
    assert client.get("/calls/does-not-exist").status_code == 404


def microphone_session(lines=("my real address is 12 Elm Street",)):
    """A microphone call, driven through the same logging path as the worker."""
    store = get_store()
    main.open_call_record("mic-call-0001", "microphone")
    for index, text in enumerate(lines):
        main.record_event(main.TranscriptEvent(
            speaker="unknown", text=text, is_final=True, t=float(index), call_id="mic-call-0001",
        ))
    main.record_event(main.system_event(main.CALL_ENDED, "mic-call-0001"))
    return store


def test_live_microphone_words_are_not_stored_by_default():
    store = microphone_session()
    incident = Incident(**CLEAN, evidence={"injury": "nobody is injured at 12 Elm Street"})
    store.record_review(
        call_id="mic-call-0001", incident=incident, decision=evaluate_incident(incident),
        action="confirmed", chosen_destination="cress", reason="",
    )

    call = store.call("mic-call-0001")

    assert call["outcome"] == "ended"
    assert call["transcript_stored"] is False
    assert call["segments"] == []
    # The answers are kept; the quoted words are not.
    assert call["decisions"][0]["incident"]["injury"] is False
    assert call["decisions"][0]["incident"]["evidence"] == {}
    # Nothing that was said reached the disk (the WAL file included).
    on_disk = b"".join(f.read_bytes() for f in store.path.parent.glob("despatch.db*"))
    assert b"Elm Street" not in on_disk and b"wellbeing_check" in on_disk


def test_live_transcripts_are_stored_only_with_the_explicit_flag(monkeypatch):
    monkeypatch.setenv("DESPATCH_STORE_LIVE_TRANSCRIPTS", "1")

    store = microphone_session()

    assert [s["text"] for s in store.call("mic-call-0001")["segments"]] == [
        "my real address is 12 Elm Street"
    ]


def test_typed_transcript_review_keeps_no_evidence_quotes():
    record = review(incident={
        **CLEAN, "evidence": {"injury": "nobody is hurt"}, "location": "14 Maple Court",
    }).json()

    stored = client.get(f"/calls/{record['call_id']}").json()

    assert stored["source"] == "manual"
    assert stored["decisions"][0]["incident"]["evidence"] == {}
    assert stored["decisions"][0]["incident"]["location"] is None


def test_error_marker_closes_the_call_as_error():
    main.open_call_record("mic-call-0002", "microphone")
    main.record_event(main.system_event(main.CALL_ERROR, "mic-call-0002"))

    assert get_store().call("mic-call-0002")["outcome"] == "error"


def test_a_broken_call_log_never_interrupts_a_call(monkeypatch, caplog):
    def broken():
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(main, "get_store", broken)

    with TestClient(app) as live:
        with live.websocket_connect("/ws/transcript") as ws:
            assert live.post("/scenarios/hidden_knife/play?speed=100").json()["status"] == "started"
            events = collect_until_ended(ws)

    assert events[-1]["text"] == "__call_ended__"
    assert "Call log write failed: OperationalError" in caplog.text


# --- the store itself --------------------------------------------------------

def test_schema_is_versioned_and_reopening_keeps_the_data(tmp_path):
    path = tmp_path / "log.db"
    store = Store(path)
    store.start_call("call-0001", "script:demo")
    store.add_segment("call-0001", 0.0, "caller", "hello")
    store.close()

    reopened = Store(path)

    assert reopened.call("call-0001")["segments"][0]["text"] == "hello"
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_newer_schema_is_refused_instead_of_being_corrupted(tmp_path):
    path = tmp_path / "log.db"
    Store(path).close()
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="schema version"):
        Store(path)


def test_database_constraints_back_up_the_api_validation(tmp_path):
    """Even a caller that bypasses the API cannot store an override without a
    reason, or a 'confirmed' row that chose something else."""
    store = Store(tmp_path / "log.db")
    incident = Incident(**CLEAN)
    decision = evaluate_incident(incident)

    for action, chosen, reason in [
        ("overridden", "police", ""),
        ("overridden", "cress", "same destination"),
        ("confirmed", "police", ""),
        ("deleted", "cress", ""),
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            store.record_review(
                call_id="call-0001", incident=incident, decision=decision,
                action=action, chosen_destination=chosen, reason=reason,
            )

    # The failed inserts were rolled back as a whole: no orphan decisions.
    assert store.call("call-0001") is None or store.call("call-0001")["decisions"] == []


def test_segments_for_an_unknown_call_are_ignored(tmp_path):
    assert Store(tmp_path / "log.db").add_segment("nope-0001", 0.0, "caller", "hi") is False


def test_concurrent_writers_do_not_lose_reviews(tmp_path):
    store = Store(tmp_path / "log.db")
    incident = Incident(**CLEAN)
    decision = evaluate_incident(incident)

    def write(index):
        store.record_review(
            call_id=f"call-{index:04d}", incident=incident, decision=decision,
            action="confirmed", chosen_destination="cress", reason="",
        )

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(store.reviews(limit=None)) == 20
