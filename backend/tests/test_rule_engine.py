from app.models import Incident, Destination
from app.services.rule_engine import evaluate_incident


def test_unknown_weapon():
    incident = Incident(
        call_type="wellbeing_check",
        weapon_present=None
    )

    decision = evaluate_incident(incident)

    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.rule_id == "SCREEN-001"


def test_uncovered_incident():
    incident = Incident(
        call_type="wellbeing_check",
        weapon_present=False
    )

    decision = evaluate_incident(incident)

    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.rule_id == "RULEBOOK-ERROR"