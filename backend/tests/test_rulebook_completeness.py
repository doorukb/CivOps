"""Exhaustive check of the rulebook: every call type (and none), every
true/false/unknown safety pattern, every half-hour of a week. 6 * 81 * 336 = 163,296."""

from collections import Counter
from datetime import datetime, timedelta
from itertools import product
from zoneinfo import ZoneInfo

import pytest

from app.models import CallType, Destination, Incident
from app.services.rule_engine import evaluate_incident, load_rulebook

RULEBOOK = load_rulebook()
SAFETY = RULEBOOK["screening"]["safety_fields"]
TZ = ZoneInfo(RULEBOOK["schedule"]["timezone"])
MONDAY = datetime(2026, 11, 16, tzinfo=TZ)  # no DST change this week

CALL_TYPES = [*CallType, None]
PATTERNS = list(product([True, False, None], repeat=len(SAFETY)))
HALF_HOURS = [MONDAY + timedelta(minutes=30 * i) for i in range(7 * 48)]


@pytest.fixture(scope="module")
def outcomes():
    rows = []
    for call_type, pattern, when in product(CALL_TYPES, PATTERNS, HALF_HOURS):
        incident = Incident(call_type=call_type, timestamp=when, **dict(zip(SAFETY, pattern)))
        rows.append((pattern, evaluate_incident(incident, RULEBOOK)))
    return rows


def test_grid_size(outcomes):
    assert (len(CALL_TYPES), len(PATTERNS), len(HALF_HOURS)) == (6, 81, 336)
    assert len(outcomes) == 163_296


def test_no_rulebook_error_and_only_allowed_destinations(outcomes):
    allowed = {Destination.CRESS, Destination.CRESS_FOLLOWUP, Destination.HUMAN_REVIEW}
    for _, decision in outcomes:
        assert decision.rule_id != "RULEBOOK-ERROR"
        assert decision.destination in allowed


def test_safety_answers_take_precedence(outcomes):
    for pattern, decision in outcomes:
        if True in pattern:
            assert decision.rule_id == "SAFETY-ESCALATION"
        elif None in pattern:  # any unknown, once no answer is true
            assert decision.rule_id == "SCREEN-INCOMPLETE"


def test_cress_only_when_all_four_answers_are_false(outcomes):
    for pattern, decision in outcomes:
        if decision.destination == Destination.CRESS:
            assert pattern == (False,) * 4


def test_every_rule_fires(outcomes):
    fired = Counter(decision.rule_id for _, decision in outcomes)
    expected = {r["id"] for r in RULEBOOK["rules"]} | {
        RULEBOOK["screening"]["escalation"]["id"],
        RULEBOOK["screening"]["incomplete"]["id"],
        "CONTEXT-INCOMPLETE",
    }
    assert expected <= set(fired)


def clean(hour, minute, transcript=None):
    incident = Incident(
        call_type=CallType.WELLBEING_CHECK,
        timestamp=MONDAY.replace(hour=hour, minute=minute),
        **{f: False for f in SAFETY},
    )
    return evaluate_incident(incident, RULEBOOK, transcript)


@pytest.mark.parametrize(
    "hour, minute, destination",
    [
        (7, 59, Destination.CRESS_FOLLOWUP),
        (8, 0, Destination.CRESS),
        (15, 59, Destination.CRESS),
        (16, 0, Destination.CRESS_FOLLOWUP),
    ],
)
def test_duty_hour_boundaries(hour, minute, destination):
    assert clean(hour, minute).destination == destination


def test_tripwire_overrides_clean_fields():
    decision = clean(10, 0, transcript="He just pulled a knife.")
    assert decision.rule_id == "TRANSCRIPT-TRIPWIRE"
    assert decision.destination == Destination.HUMAN_REVIEW
