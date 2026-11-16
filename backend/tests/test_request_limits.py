"""Every free-text field and list in a request body has a ceiling (S-03)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    MAX_AUDIT_RECORDS,
    MAX_EVENT_TEXT_CHARS,
    MAX_SIMULATION_INCIDENTS,
    MAX_TRANSCRIPT_CHARS,
)

client = TestClient(app)

INCIDENT = {
    "call_type": "wellbeing_check",
    "weapon_present": False,
    "violence": False,
    "injury": False,
    "immediate_danger": False,
    "timestamp": "2026-11-16T14:30:00-05:00",
}
RECORD = {"call_id": "C-1", "incident": INCIDENT, "actual_destination": "police"}


def test_evaluate_rejects_oversized_transcript():
    body = {"incident": INCIDENT, "transcript": "a" * (MAX_TRANSCRIPT_CHARS + 1)}
    assert client.post("/calls/evaluate", json=body).status_code == 422

    body["transcript"] = "a" * MAX_TRANSCRIPT_CHARS
    assert client.post("/calls/evaluate", json=body).status_code == 200


@pytest.mark.parametrize("path", ["/calls/extract", "/calls/screen"])
def test_extract_and_screen_reject_oversized_transcript(path):
    body = {"transcript": "a" * (MAX_TRANSCRIPT_CHARS + 1)}
    assert client.post(path, json=body).status_code == 422


def test_audit_rejects_oversized_transcript_and_call_id():
    long_text = {**RECORD, "transcript": "a" * (MAX_TRANSCRIPT_CHARS + 1)}
    assert client.post("/audit/run", json={"records": [long_text]}).status_code == 422

    long_id = {**RECORD, "call_id": "x" * 65}
    assert client.post("/audit/run", json={"records": [long_id]}).status_code == 422


def test_audit_rejects_too_many_records():
    body = {"records": [RECORD] * (MAX_AUDIT_RECORDS + 1)}
    assert client.post("/audit/run", json=body).status_code == 422


def test_simulation_rejects_too_many_incidents():
    body = {"config": {}, "incidents": [INCIDENT] * (MAX_SIMULATION_INCIDENTS + 1)}
    assert client.post("/simulation/run", json=body).status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"text": "a" * (MAX_EVENT_TEXT_CHARS + 1)},
        {"speaker": "s" * 33},
    ],
)
def test_transcript_event_rejects_oversized_fields(patch):
    event = {"speaker": "caller", "text": "hello", "is_final": True, "t": 0.0, **patch}
    assert client.post("/transcript/event", json=event).status_code == 422


def test_incident_rejects_oversized_evidence():
    incident = {**INCIDENT, "evidence": {"injury": "a" * (MAX_EVENT_TEXT_CHARS + 1)}}
    assert client.post("/calls/evaluate", json={"incident": incident}).status_code == 422

    too_many = {**INCIDENT, "evidence": {f"field_{i}": "quote" for i in range(17)}}
    assert client.post("/calls/evaluate", json={"incident": too_many}).status_code == 422
