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