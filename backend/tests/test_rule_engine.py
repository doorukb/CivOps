from app.models import Incident, Destination
from app.services.rule_engine import evaluate_incident


def make_incident(**overrides):
    data = {
        "call_type": "wellbeing_check",
        "weapon_present": False,
        "violence": False,
        "injury": False,
        "immediate_danger": False,
        "timestamp": "2026-11-16T14:30:00-05:00"
    }
    data.update(overrides)
    return Incident(**data)


def test_eligible_call():
    decision = evaluate_incident(make_incident())
    assert decision.destination == Destination.CRESS
    assert decision.rule_id == "CRESS-001"


def test_after_hours():
    incident = make_incident(
        timestamp="2026-11-16T19:30:00-05:00"
    )
    decision = evaluate_incident(incident)
    assert decision.destination == Destination.CRESS_FOLLOWUP


def test_weapon_escalation():
    incident = make_incident(weapon_present=True)
    decision = evaluate_incident(incident)
    assert decision.rule_id == "SAFETY-ESCALATION"


def test_multiple_safety_flags():
    incident = make_incident(
        weapon_present=True,
        violence=True
    )
    decision = evaluate_incident(incident)
    assert decision.rule_id == "SAFETY-ESCALATION"


def test_unknown_safety():
    incident = make_incident(injury=None)
    decision = evaluate_incident(incident)
    assert decision.rule_id == "SCREEN-INCOMPLETE"
    assert "injury" in decision.missing_information


def test_ineligible_type():
    incident = make_incident(call_type="noise_complaint")
    decision = evaluate_incident(incident)
    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.rule_id == "REVIEW-001"


def test_weekend():
    incident = make_incident(
        timestamp="2026-11-14T14:30:00-05:00"
    )
    decision = evaluate_incident(incident)
    assert decision.destination == Destination.CRESS_FOLLOWUP

from copy import deepcopy

from app.services.rule_engine import load_rulebook


def test_eligibility_metadata():
    decision = evaluate_incident(make_incident())

    assert decision.eligible is True
    assert decision.on_duty is True
    assert decision.source is not None


def test_alternative_schedule():
    rulebook = deepcopy(load_rulebook())

    # Extend the closing time from 4 PM to 8 PM
    rulebook["schedule"]["end_hour"] = 20

    incident = make_incident(
        timestamp="2026-11-16T19:30:00-05:00"
    )

    baseline = evaluate_incident(incident)
    extended = evaluate_incident(incident, rulebook)

    assert baseline.destination == Destination.CRESS_FOLLOWUP
    assert baseline.eligible is True
    assert baseline.on_duty is False

    assert extended.destination == Destination.CRESS
    assert extended.eligible is True
    assert extended.on_duty is True

def test_tripwire_overrides_extraction():
    incident = make_incident(
        weapon_present=False,
        violence=False,
        injury=False,
        immediate_danger=False
    )

    decision = evaluate_incident(
        incident,
        transcript="My neighbor has a knife."
    )

    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.rule_id == "TRANSCRIPT-TRIPWIRE"