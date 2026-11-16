"""Autonomy in one direction only (G-05).

The system may raise urgency by itself. Lowering it takes a person: a
recommendation that sends a call to CRESS is provisional while any "no" it
rests on was proposed by the model and not confirmed by a human.
"""

from datetime import datetime, timedelta
from itertools import product

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import SAFETY_FIELDS, CallType, Destination, Incident
from app.rulebook import load_rulebook
from app.services.rule_engine import evaluate_incident

client = TestClient(app)
RULEBOOK = load_rulebook()
MONDAY = datetime(2026, 11, 16, tzinfo=RULEBOOK.schedule.tzinfo)
ALL_MODEL = dict.fromkeys(SAFETY_FIELDS, "model")


def incident(provenance=None, hour=14, **overrides) -> Incident:
    data = {
        "call_type": "wellbeing_check",
        **dict.fromkeys(SAFETY_FIELDS, False),
        "timestamp": MONDAY.replace(hour=hour),
        "provenance": provenance or {},
        **overrides,
    }
    return Incident(**data)


def test_model_proposed_negatives_make_a_cress_recommendation_provisional():
    decision = evaluate_incident(incident(ALL_MODEL))

    assert decision.destination == Destination.CRESS
    assert decision.rule_id == "CRESS-001"  # the rule outcome itself is unchanged
    assert decision.provisional is True
    assert decision.needs_confirmation == list(SAFETY_FIELDS)


def test_after_hours_follow_up_is_provisional_too():
    decision = evaluate_incident(incident(ALL_MODEL, hour=19))

    assert decision.destination == Destination.CRESS_FOLLOWUP
    assert decision.provisional is True


def test_only_the_unconfirmed_answers_are_listed():
    provenance = {**dict.fromkeys(SAFETY_FIELDS, "human"), "injury": "model"}

    decision = evaluate_incident(incident(provenance))

    assert decision.provisional is True
    assert decision.needs_confirmation == ["injury"]


@pytest.mark.parametrize(
    "provenance",
    [{}, dict.fromkeys(SAFETY_FIELDS, "human")],
    ids=["no provenance (audit, simulator, hand-filled)", "human-confirmed"],
)
def test_human_answers_are_final(provenance):
    decision = evaluate_incident(incident(provenance))

    assert decision.destination == Destination.CRESS
    assert decision.provisional is False
    assert decision.needs_confirmation == []


def test_a_model_proposed_yes_escalates_without_confirmation():
    """Raising urgency needs no human."""
    decision = evaluate_incident(incident(ALL_MODEL, weapon_present=True))

    assert decision.rule_id == "SAFETY-ESCALATION"
    assert decision.provisional is False


@pytest.mark.parametrize(
    "overrides, transcript, rule_id",
    [
        ({"injury": None}, None, "SCREEN-INCOMPLETE"),
        ({"call_type": "noise_complaint"}, None, "REVIEW-001"),
        ({"call_type": None}, None, "CONTEXT-INCOMPLETE"),
        ({}, "He has a knife.", "TRANSCRIPT-TRIPWIRE"),
    ],
)
def test_decisions_that_already_go_to_a_human_are_never_provisional(
    overrides, transcript, rule_id
):
    decision = evaluate_incident(incident(ALL_MODEL, **overrides), transcript=transcript)

    assert decision.rule_id == rule_id
    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.provisional is False


def test_invariant_over_every_call_type_and_half_hour_of_the_week():
    """With all four answers model-proposed "no": every recommendation that
    leaves the human dispatcher is provisional, and nothing else is."""
    half_hours = [MONDAY + timedelta(minutes=30 * i) for i in range(7 * 48)]
    seen = set()

    for call_type, when in product(CallType, half_hours):
        decision = evaluate_incident(
            incident(ALL_MODEL, call_type=call_type, timestamp=when), RULEBOOK
        )
        away_from_human = decision.destination != Destination.HUMAN_REVIEW
        assert decision.provisional is away_from_human
        seen.add((decision.destination, decision.provisional))

    assert seen == {
        (Destination.CRESS, True),
        (Destination.CRESS_FOLLOWUP, True),
        (Destination.HUMAN_REVIEW, False),
    }


def test_provenance_only_accepts_safety_fields_and_known_sources():
    with pytest.raises(ValidationError):
        Incident(provenance={"call_type": "model"})
    with pytest.raises(ValidationError):
        Incident(provenance={"injury": "oracle"})


def test_api_reports_provisional_until_a_person_confirms():
    body = {
        "incident": {
            "call_type": "wellbeing_check",
            **dict.fromkeys(SAFETY_FIELDS, False),
            "timestamp": "2026-11-16T14:00:00-05:00",
            "provenance": ALL_MODEL,
        }
    }

    first = client.post("/calls/evaluate", json=body).json()
    assert (first["destination"], first["provisional"]) == ("cress", True)
    assert first["needs_confirmation"] == list(SAFETY_FIELDS)

    body["incident"]["provenance"] = dict.fromkeys(SAFETY_FIELDS, "human")
    confirmed = client.post("/calls/evaluate", json=body).json()
    assert (confirmed["destination"], confirmed["provisional"]) == ("cress", False)


def test_extractor_marks_what_the_model_proposed(monkeypatch):
    from types import SimpleNamespace

    import app.services.extractor as extractor

    canned = extractor.ExtractedIncident(
        call_type="wellbeing_check",
        caller_requests_cress=None,
        weapon_present={"value": False, "evidence": "there are no weapons"},
        violence={"value": True, "evidence": "he pushed her"},
        injury={"value": None, "evidence": None},
        immediate_danger={"value": False, "evidence": "made-up quote"},
    )
    monkeypatch.setattr(
        extractor, "_client",
        lambda: SimpleNamespace(
            messages=SimpleNamespace(parse=lambda **_: SimpleNamespace(parsed_output=canned))
        ),
    )

    result = extractor.extract_incident("Caller: there are no weapons but he pushed her")

    # Only answers that survived the checks carry provenance.
    assert result.provenance == {"weapon_present": "model", "violence": "model"}
    assert result.unconfirmed_negatives() == ["weapon_present"]
