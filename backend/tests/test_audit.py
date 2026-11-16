import pytest

from app.models import AuditRecord, Destination, Incident
from app.services.audit import audit_calls


def test_audit_record():
    # Create a fictional call record
    record = AuditRecord(
        call_id="CALL-001",
        incident=Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T14:30:00-05:00"
        ),
        actual_destination=Destination.POLICE
    )

    # Verify that the record stores the correct information
    assert record.call_id == "CALL-001"
    assert record.actual_destination == Destination.POLICE

def test_audit_calls():
    record = AuditRecord(
        call_id="CALL-001",
        incident=Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T14:30:00-05:00"
        ),
        actual_destination=Destination.POLICE
    )

    results = audit_calls([record])

    assert len(results) == 1
    assert results[0]["call_id"] == "CALL-001"
    assert results[0]["actual_destination"] == "police"
    assert results[0]["recommended_destination"] == "cress"
    assert results[0]["rule_id"] == "CRESS-001"

def test_missed_cress_referral():
    record = AuditRecord(
        call_id="CALL-002",
        incident=Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T14:30:00-05:00"
        ),
        actual_destination=Destination.POLICE
    )

    results = audit_calls([record])

    assert results[0]["could_have_gone_to_cress"] is True
    assert results[0]["sent_to_cress_appropriately"] is False


def test_audit_replay_runs_tripwire_on_transcript():
    # All-clear fields, but the transcript mentions a knife: the replay must
    # flag it like Live Call does, not call it a missed CRESS referral.
    record = AuditRecord(
        call_id="CALL-003",
        incident=Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp="2026-11-16T14:30:00-05:00"
        ),
        actual_destination=Destination.POLICE,
        transcript="He said he has a knife."
    )

    result = audit_calls([record])[0]

    assert result["rule_id"] == "TRANSCRIPT-TRIPWIRE"
    assert result["could_have_gone_to_cress"] is False

from app.services.audit import summarize_audit


def test_audit_summary():
    records = [
        AuditRecord(
            call_id="CALL-001",
            incident=Incident(
                call_type="wellbeing_check",
                weapon_present=False,
                violence=False,
                injury=False,
                immediate_danger=False,
                timestamp="2026-11-16T14:30:00-05:00"
            ),
            actual_destination=Destination.POLICE
        ),
        AuditRecord(
            call_id="CALL-002",
            incident=Incident(
                call_type="wellbeing_check",
                weapon_present=False,
                violence=False,
                injury=False,
                immediate_danger=False,
                timestamp="2026-11-16T15:00:00-05:00"
            ),
            actual_destination=Destination.CRESS
        )
    ]

    results = audit_calls(records)
    summary = summarize_audit(results)

    assert summary["total_calls"] == 2
    assert summary["could_have_gone_to_cress"] == 1
    assert summary["sent_to_cress_appropriately"] == 1
    assert summary["should_not_have_gone_to_cress"] == 0

@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("2026-11-16T15:59:00-05:00", False),
        ("2026-11-16T16:00:00-05:00", True),
        ("2026-11-16T19:59:00-05:00", True),
        ("2026-11-16T20:00:00-05:00", False),
        ("2026-11-14T18:00:00-05:00", True),
    ]
)
def test_evening_review_window(timestamp, expected):
    record = AuditRecord(
        call_id="CALL-TEST",
        incident=Incident(
            call_type="wellbeing_check",
            weapon_present=False,
            violence=False,
            injury=False,
            immediate_danger=False,
            timestamp=timestamp
        ),
        actual_destination=Destination.POLICE
    )

    results = audit_calls([record])

    assert results[0]["eligible_after_hours"] is expected

# --- review window, line breakdown and demo parameters (R-04, G-03, G-07) ----

def make_record(call_id, timestamp, actual="police", **overrides):
    incident = {
        "call_type": "wellbeing_check",
        "weapon_present": False,
        "violence": False,
        "injury": False,
        "immediate_danger": False,
        "timestamp": timestamp,
        **overrides,
    }
    return AuditRecord(call_id=call_id, incident=Incident(**incident), actual_destination=actual)


def test_review_window_follows_the_rulebook_shift_end():
    from app.rulebook import load_rulebook
    from app.services.audit import review_window, summarize_audit

    shipped = load_rulebook()
    later = shipped.with_changes(schedule={"end_hour": 18})
    past_midnight = shipped.with_changes(schedule={"start_hour": 9, "end_hour": 22})

    assert review_window(shipped.schedule)["label"] == "4 PM to 8 PM"
    assert review_window(later.schedule)["label"] == "6 PM to 10 PM"
    assert review_window(past_midnight.schedule)["label"] == "10 PM to 2 AM"

    # 6:30 PM Monday: after hours under the shipped rulebook, on duty until 6 PM under `later`.
    record = make_record("C-1", "2026-11-16T18:30:00-05:00")
    assert summarize_audit(audit_calls([record]))["eligible_after_hours"] == 1
    moved = audit_calls([record], later)
    assert moved[0]["eligible_after_hours"] is True and moved[0]["local_hour"] == 18
    # 4:30 PM is on duty once the shift ends at 6 PM, so it leaves the group.
    assert audit_calls([make_record("C-2", "2026-11-16T16:30:00-05:00")], later)[0][
        "eligible_after_hours"
    ] is False


def test_review_window_wraps_past_midnight():
    from app.rulebook import load_rulebook

    late = load_rulebook().with_changes(schedule={"start_hour": 9, "end_hour": 22})
    one_am = audit_calls([make_record("C-1", "2026-11-17T01:00:00-05:00")], late)[0]
    three_am = audit_calls([make_record("C-2", "2026-11-17T03:00:00-05:00")], late)[0]

    assert one_am["eligible_after_hours"] is True
    assert three_am["eligible_after_hours"] is False


def test_weekend_calls_in_the_window_count_and_that_is_documented():
    from app.rulebook import load_rulebook
    from app.services.audit import review_window

    saturday_5pm = audit_calls([make_record("C-1", "2026-11-21T17:00:00-05:00")])[0]

    assert saturday_5pm["eligible_after_hours"] is True
    assert review_window(load_rulebook().schedule)["days"] == "every day"


def test_summary_breaks_missed_referrals_down_by_line():
    from app.services.audit import summarize_audit

    records = [
        make_record("C-1", "2026-11-16T10:00:00-05:00", source_line="non_emergency"),
        make_record("C-2", "2026-11-16T10:05:00-05:00", source_line="non_emergency"),
        make_record("C-3", "2026-11-16T10:10:00-05:00", source_line="911"),
        make_record("C-4", "2026-11-16T10:15:00-05:00"),
        make_record("C-5", "2026-11-16T10:20:00-05:00", actual="cress", source_line="911"),
    ]

    summary = summarize_audit(audit_calls(records))

    assert summary["could_have_gone_to_cress"] == 4
    assert summary["could_have_gone_by_line"] == {"non_emergency": 2, "911": 1, "unknown": 1}
    assert summary["by_rule"] == {"CRESS-001": 5}
    assert summary["rulebook_version"]


def test_the_line_never_changes_a_recommendation():
    """Document-only scope: the line is recorded, no rule reads it."""
    by_line = [
        audit_calls([make_record("C", "2026-11-16T10:00:00-05:00", source_line=line)])[0]
        for line in ("911", "non_emergency", None)
    ]

    assert {(r["rule_id"], r["recommended_destination"]) for r in by_line} == {
        ("CRESS-001", "cress")
    }


def test_unknown_line_value_is_rejected():
    with pytest.raises(ValueError):
        Incident(source_line="carrier pigeon")


def test_demo_audit_accepts_bounded_parameters():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    small = client.get("/audit/demo?count=40&seed=7&year=2026&month=2").json()
    assert small["dataset"]["count"] == 40 and small["dataset"]["seed"] == 7
    assert all(r["timestamp"].startswith("2026-02") for r in small["results"])
    assert small["summary"]["review_window"]["label"] == "4 PM to 8 PM"
    assert client.get("/audit/demo?count=40&seed=7&year=2026&month=2").json() == small

    for bad in ("count=0", "count=5001", "month=13", "seed=-1", "year=1800"):
        assert client.get(f"/audit/demo?{bad}").status_code == 422


def test_audit_rows_carry_reason_source_and_call_type():
    row = audit_calls([make_record("C-1", "2026-11-16T10:00:00-05:00")])[0]

    assert row["reason"] and row["source"] and row["call_type"] == "wellbeing_check"
