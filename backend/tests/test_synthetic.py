from collections import Counter

from app.models import Destination
from app.services.rule_engine import evaluate_incident, load_rulebook
from app.services.synthetic import (
    SAFETY_FIELDS,
    TRUE_SAFETY_RATE,
    UNKNOWN_SAFETY_RATE,
    cress_on_duty,
    generate_synthetic_month,
)


def test_synthetic_month():
    records = generate_synthetic_month(count=100)

    assert len(records) == 100
    assert len(set(r.call_id for r in records)) == 100
    assert all(r.call_id.startswith("SYN-") for r in records)


def test_same_seed_same_month():
    assert generate_synthetic_month(seed=7) == generate_synthetic_month(seed=7)
    assert generate_synthetic_month(seed=7) != generate_synthetic_month(seed=8)


def test_cress_only_when_cress_works():
    for r in generate_synthetic_month(count=2000):
        if r.actual_destination == Destination.CRESS:
            assert cress_on_duty(r.incident.timestamp)


def test_injury_goes_to_fire_ems_otherwise_police_or_cress():
    for r in generate_synthetic_month(count=2000):
        if r.incident.injury is True:
            assert r.actual_destination in (
                Destination.FIRE_EMS, Destination.CRESS  # CRESS = misroute
            )
        else:
            assert r.actual_destination in (
                Destination.POLICE, Destination.CRESS
            )


def test_safety_answers_are_rare_and_single():
    records = generate_synthetic_month(count=4000)
    counts = Counter()

    for r in records:
        values = [getattr(r.incident, f) for f in SAFETY_FIELDS]
        assert values.count(True) + values.count(None) <= 1
        counts["true"] += True in values
        counts["unknown"] += None in values

    assert abs(counts["true"] / 4000 - TRUE_SAFETY_RATE) < 0.02
    assert abs(counts["unknown"] / 4000 - UNKNOWN_SAFETY_RATE) < 0.02


def test_default_month_produces_safety_and_incomplete_outcomes():
    rulebook = load_rulebook()
    rules = Counter(
        evaluate_incident(r.incident, rulebook).rule_id
        for r in generate_synthetic_month()
    )
    assert rules["SAFETY-ESCALATION"] > 0
    assert rules["SCREEN-INCOMPLETE"] > 0
