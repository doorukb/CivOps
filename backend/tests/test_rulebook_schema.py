"""The rulebook file is validated at load, and the loader enforces the
safety invariants on the file itself (R-02, G-03)."""

import time
from copy import deepcopy

import pytest
import yaml
from pydantic import ValidationError

from app.models import AuditRecord, CallType, Destination, Incident
from app.rulebook import (
    ROUTABLE_DESTINATIONS,
    RULEBOOK_PATH,
    Rulebook,
    RulebookError,
    load_rulebook,
    parse_rulebook,
)
from app.services.audit import audit_calls
from app.services.rule_engine import evaluate_incident

SHIPPED = yaml.safe_load(RULEBOOK_PATH.read_text(encoding="utf-8"))


def broken(mutate) -> str:
    data = deepcopy(SHIPPED)
    mutate(data)
    return yaml.safe_dump(data)


def test_shipped_rulebook_validates():
    rulebook = load_rulebook()

    assert rulebook.version == SHIPPED["version"]
    assert [rule.id for rule in rulebook.rules] == ["CRESS-001", "CRESS-002", "REVIEW-001"]
    assert rulebook.eligible_call_types == (
        CallType.WELLBEING_CHECK, CallType.DISTURBANCE, CallType.SUSPICIOUS,
    )


def test_every_rule_and_safety_outcome_cites_a_source():
    rulebook = load_rulebook()

    for item in (*rulebook.rules, *rulebook.safety_outcomes()):
        assert item.source.strip(), item.id


def test_rulebook_is_loaded_once_and_cannot_be_mutated():
    rulebook = load_rulebook()

    assert load_rulebook() is rulebook  # cached: no disk read per evaluation
    with pytest.raises(ValidationError):
        rulebook.schedule.end_hour = 20
    with pytest.raises(ValidationError):
        rulebook.version = "tampered"
    with pytest.raises(AttributeError):
        rulebook.eligible_call_types.append(CallType.OTHER)


def test_with_changes_returns_a_validated_copy():
    base = load_rulebook()
    changed = base.with_changes(schedule={"end_hour": 20})

    assert changed.schedule.end_hour == 20
    assert base.schedule.end_hour == 16
    with pytest.raises(ValidationError):
        base.with_changes(schedule={"end_hour": 3})  # ends before it starts


@pytest.mark.parametrize(
    "mutate, problem",
    [
        # A typo in a condition key used to mean "this rule silently never matches".
        (lambda d: d["rules"][0]["conditions"].update(on_dutty=True), "on_dutty"),
        (lambda d: d["rules"][1].update(id="CRESS-001"), "duplicate rule ids"),
        (lambda d: d["rules"][0].update(destination="nowhere"), "destination"),
        (lambda d: d["rules"][0].pop("source"), "source"),
        (lambda d: d["schedule"].update(end_hour=7), "end_hour must be greater"),
        (lambda d: d["schedule"].update(weekdays=[0, 7]), "weekdays"),
        (lambda d: d["schedule"].update(timezone="Mars/Olympus"), "unknown timezone"),
        (lambda d: d["screening"].update(safety_fields=["weapon_present", "mood"]), "mood"),
        (lambda d: d.update(eligible_call_types=["wellbeing_check", "picnic"]), "picnic"),
        (lambda d: d.update(rules=[]), "rules"),
        (lambda d: d.update(colour="blue"), "colour"),
    ],
)
def test_broken_rulebook_fails_with_a_clear_error(mutate, problem):
    with pytest.raises(RulebookError) as error:
        parse_rulebook(broken(mutate))

    assert problem in str(error.value)


def test_unparseable_yaml_is_a_rulebook_error():
    with pytest.raises(RulebookError):
        parse_rulebook("rules: [unclosed")


@pytest.mark.parametrize("stage", ["tripwire", "escalation", "incomplete", "context_incomplete"])
@pytest.mark.parametrize("destination", ["cress", "cress_followup", "police"])
def test_safety_outcomes_can_only_go_to_a_human(stage, destination):
    """Invariant: every safety path ends in human_review. Editing the YAML
    cannot change that."""
    with pytest.raises(RulebookError) as error:
        parse_rulebook(broken(lambda d: d["screening"][stage].update(destination=destination)))

    assert "must go to human_review" in str(error.value)


@pytest.mark.parametrize("destination", ["police", "fire_ems", "crisis"])
def test_no_rule_can_route_to_police_fire_or_crisis(destination):
    """Invariant: nothing routes to police on its own."""
    assert Destination(destination) not in ROUTABLE_DESTINATIONS

    with pytest.raises(RulebookError) as error:
        parse_rulebook(broken(lambda d: d["rules"][0].update(destination=destination)))

    assert "reserved" in str(error.value)


def clean_incident(**overrides) -> Incident:
    data = {
        "call_type": "wellbeing_check",
        "weapon_present": False,
        "violence": False,
        "injury": False,
        "immediate_danger": False,
        "timestamp": "2026-11-16T14:30:00-05:00",
        **overrides,
    }
    return Incident(**data)


def doctored(mutate) -> Rulebook:
    return parse_rulebook(broken(mutate))


def test_no_matching_rule_goes_to_a_human():
    rulebook = doctored(lambda d: d.update(rules=[d["rules"][2]]))  # only REVIEW-001

    decision = evaluate_incident(clean_incident(), rulebook)

    assert decision.rule_id == "RULEBOOK-ERROR"
    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.reason == "No matching eligibility rule."


def test_conflicting_rules_go_to_a_human():
    def add_conflict(data):
        clash = deepcopy(data["rules"][0])
        clash.update(id="CRESS-CLASH", destination="cress_followup")
        data["rules"].append(clash)

    decision = evaluate_incident(clean_incident(), doctored(add_conflict))

    assert decision.rule_id == "RULEBOOK-ERROR"
    assert decision.destination == Destination.HUMAN_REVIEW
    assert decision.reason == "Conflicting eligibility rules."


def test_lower_priority_number_wins():
    def add_override(data):
        data["rules"][0]["priority"] = 2
        data["rules"].append({
            "id": "CRESS-HOLD",
            "priority": 1,
            "conditions": {"eligible_call_type": True, "on_duty": True},
            "destination": "human_review",
            "reason": "Held for review.",
            "source": "Test",
        })

    assert evaluate_incident(clean_incident(), doctored(add_override)).rule_id == "CRESS-HOLD"


def test_naive_timestamp_goes_to_context_incomplete():
    decision = evaluate_incident(clean_incident(timestamp="2026-11-16T14:30:00"))

    assert decision.rule_id == "CONTEXT-INCOMPLETE"
    assert decision.missing_information == ["timestamp_timezone"]


@pytest.mark.parametrize(
    "overrides, transcript, rule_id",
    [
        ({}, "He has a knife.", "TRANSCRIPT-TRIPWIRE"),
        ({"violence": True}, None, "SAFETY-ESCALATION"),
        ({"injury": None}, None, "SCREEN-INCOMPLETE"),
        ({"call_type": None}, None, "CONTEXT-INCOMPLETE"),
        ({}, None, "CRESS-001"),
    ],
)
def test_every_decision_carries_source_and_version(overrides, transcript, rule_id):
    decision = evaluate_incident(clean_incident(**overrides), transcript=transcript)

    assert decision.rule_id == rule_id
    assert decision.source
    assert decision.rulebook_version == load_rulebook().version


def test_audit_replay_no_longer_reparses_the_rulebook_per_record():
    """5,000 records used to cost ~2 ms each in YAML parsing alone (~10 s)."""
    records = [
        AuditRecord(
            call_id=f"C-{i}", incident=clean_incident(), actual_destination="police"
        )
        for i in range(5_000)
    ]

    started = time.perf_counter()
    results = audit_calls(records)
    elapsed = time.perf_counter() - started

    assert len(results) == 5_000
    assert results[0]["source"]
    assert elapsed < 5.0  # generous ceiling for slow CI; typically well under 1 s
