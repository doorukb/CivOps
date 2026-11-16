from fastapi.testclient import TestClient

from app.main import app
from app.models import Incident

client = TestClient(app)


def test_evaluate_normal_call():
    response = client.post(
        "/calls/evaluate",
        json={
            "incident": {
                "call_type": "wellbeing_check",
                "weapon_present": False,
                "violence": False,
                "injury": False,
                "immediate_danger": False,
                "timestamp": "2026-11-16T14:30:00-05:00"
            },
            "transcript": "I'm worried about my neighbor."
        }
    )

    assert response.status_code == 200
    assert response.json()["destination"] == "cress"


def test_evaluate_tripwire():
    response = client.post(
        "/calls/evaluate",
        json={
            "incident": {
                "call_type": "wellbeing_check",
                "weapon_present": False,
                "violence": False,
                "injury": False,
                "immediate_danger": False,
                "timestamp": "2026-11-16T14:30:00-05:00"
            },
            "transcript": "My neighbor has a knife."
        }
    )

    assert response.status_code == 200
    assert response.json()["destination"] == "human_review"
    assert response.json()["rule_id"] == "TRANSCRIPT-TRIPWIRE"

def test_reject_invalid_incident():
    response = client.post(
        "/calls/evaluate",
        json={
            "incident": {
                "call_type": "invalid_call_type"
            }
        }
    )

    assert response.status_code == 422

def test_monthly_audit_endpoint():
    response = client.post(
        "/audit/run",
        json={
            "records": [
                {
                    "call_id": "CALL-001",
                    "incident": {
                        "call_type": "wellbeing_check",
                        "weapon_present": False,
                        "violence": False,
                        "injury": False,
                        "immediate_danger": False,
                        "timestamp": "2026-11-16T14:30:00-05:00"
                    },
                    "actual_destination": "police"
                }
            ]
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert data["summary"]["total_calls"] == 1
    assert data["summary"]["could_have_gone_to_cress"] == 1
    assert data["results"][0]["rule_id"] == "CRESS-001"

def test_audit_demo_endpoint():
    response = client.get("/audit/demo")

    assert response.status_code == 200

    data = response.json()

    assert data["dataset"]["synthetic"] is True
    assert data["dataset"]["calibrated_to_leap"] is False
    assert "fitted to the coverage totals" in data["dataset"]["arrival_pattern"]
    assert "invented" in data["dataset"]["arrival_pattern"]
    assert data["summary"]["total_calls"] == 250
    assert len(data["results"]) == 250

def test_simulation_endpoint():
    response = client.post(
        "/simulation/run",
        json={
            "config": {
                "teams": 1,
                "average_duration_minutes": 60
            },
            "incidents": [
                {
                    "call_type": "wellbeing_check",
                    "weapon_present": False,
                    "violence": False,
                    "injury": False,
                    "immediate_danger": False,
                    "timestamp": "2026-11-16T10:00:00-05:00"
                },
                {
                    "call_type": "wellbeing_check",
                    "weapon_present": False,
                    "violence": False,
                    "injury": False,
                    "immediate_danger": False,
                    "timestamp": "2026-11-16T10:10:00-05:00"
                }
            ]
        }
    )

    assert response.status_code == 200

    result = response.json()

    assert result["total_calls"] == 2
    assert result["eligible_calls"] == 2
    assert result["handled_calls"] == 1
    assert result["missed_busy"] == 1

def test_extract_endpoint(monkeypatch):
    def fake_extract(transcript):
        return Incident(
            call_type="disturbance",
            weapon_present=False,
            violence=None,
            injury=False,
            immediate_danger=None,
            evidence={
                "weapon_present": "there are no weapons",
                "injury": "nobody is injured"
            }
        )

    monkeypatch.setattr(
        "app.main.extract_incident",
        fake_extract
    )

    response = client.post(
        "/calls/extract",
        json={"transcript": "Fictional test transcript"}
    )

    assert response.status_code == 200

    data = response.json()

    assert data["call_type"] == "disturbance"
    assert data["weapon_present"] is False
    assert data["violence"] is None
    assert data["evidence"]["injury"] == "nobody is injured"