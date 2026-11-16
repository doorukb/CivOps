"""Offline regression test of the three scripted demo calls (E-03).

Replays a stored model proposal for each script through the deterministic
checks and the rulebook, at the three simulated call times the console offers.
No paid calls. While eval/fixtures/demo_scripts.json says "recorded": false it
holds a hand-written ideal extraction; after `python -m eval.record_demo_fixtures
--yes` it holds real model output and this same test guards it.
"""

import json
from datetime import datetime

import pytest

from app.models import SAFETY_FIELDS
from app.services.call_session import SCENARIOS
from app.services.extractor import ExtractedIncident, verify
from app.services.rule_engine import evaluate_incident
from eval.record_demo_fixtures import FIXTURE, transcript_of

FIXTURES = json.loads(FIXTURE.read_text(encoding="utf-8"))

# The console's "simulated call time" choices (America/New_York).
SIM_TIMES = {
    "mon_2pm": datetime.fromisoformat("2026-11-16T14:00:00-05:00"),
    "mon_730pm": datetime.fromisoformat("2026-11-16T19:30:00-05:00"),
    "sat_11am": datetime.fromisoformat("2026-11-21T11:00:00-05:00"),
}

# What the demo is supposed to show: (rule ID, destination) per script and time.
EXPECTED = {
    "routine_wellbeing": {
        "mon_2pm": ("CRESS-001", "cress"),
        "mon_730pm": ("CRESS-002", "cress_followup"),
        "sat_11am": ("CRESS-002", "cress_followup"),
    },
    "incomplete_screening": dict.fromkeys(SIM_TIMES, ("SCREEN-INCOMPLETE", "human_review")),
    "hidden_knife": dict.fromkeys(SIM_TIMES, ("TRANSCRIPT-TRIPWIRE", "human_review")),
}


def extracted(scenario_id: str):
    proposal = ExtractedIncident.model_validate(FIXTURES["scripts"][scenario_id]["model_output"])
    return verify(proposal, transcript_of(scenario_id))


def test_fixture_covers_every_script_and_says_where_it_came_from():
    assert set(FIXTURES["scripts"]) == set(SCENARIOS) == set(EXPECTED)
    assert isinstance(FIXTURES["recorded"], bool)
    if FIXTURES["recorded"]:
        assert FIXTURES["meta"]["model"] and FIXTURES["meta"]["extractor_prompt_sha256"]
    else:
        assert "HAND-WRITTEN" in FIXTURES["note"]


@pytest.mark.parametrize(
    "scenario_id, sim_time",
    [(s, t) for s in EXPECTED for t in SIM_TIMES],
)
def test_scripted_call_reaches_the_expected_rule(scenario_id, sim_time):
    incident = extracted(scenario_id).model_copy(update={"timestamp": SIM_TIMES[sim_time]})

    decision = evaluate_incident(incident, transcript=transcript_of(scenario_id))

    assert (decision.rule_id, decision.destination) == EXPECTED[scenario_id][sim_time]


def test_routine_call_is_provisional_until_a_person_confirms_the_negatives():
    """The demo's 'CRESS' moment must wait for a human: the four 'no' answers
    came from the model."""
    incident = extracted("routine_wellbeing").model_copy(
        update={"timestamp": SIM_TIMES["mon_2pm"]}
    )
    proposed = evaluate_incident(incident, transcript=transcript_of("routine_wellbeing"))

    confirmed = incident.model_copy(update={"provenance": dict.fromkeys(SAFETY_FIELDS, "human")})
    accepted = evaluate_incident(confirmed, transcript=transcript_of("routine_wellbeing"))

    assert (proposed.destination, proposed.provisional) == ("cress", True)
    assert proposed.needs_confirmation == list(SAFETY_FIELDS)
    assert (accepted.destination, accepted.provisional) == ("cress", False)


def test_every_quote_in_the_fixture_survives_the_evidence_and_hedge_checks():
    """If a script or a check changes so that a stored quote no longer holds,
    the demo would silently degrade to 'unknown'. Catch that here."""
    for scenario_id in SCENARIOS:
        result = extracted(scenario_id)
        assert result.downgraded == {}, (scenario_id, result.downgraded)


def test_hidden_knife_is_caught_twice_over():
    """Tripwire on the transcript AND the extracted weapon answer: either
    alone sends the call to a human."""
    incident = extracted("hidden_knife").model_copy(update={"timestamp": SIM_TIMES["mon_2pm"]})

    assert evaluate_incident(incident).rule_id == "SAFETY-ESCALATION"  # model path alone
    blank = incident.model_copy(update=dict.fromkeys(SAFETY_FIELDS, False))
    assert evaluate_incident(
        blank, transcript=transcript_of("hidden_knife")
    ).rule_id == "TRANSCRIPT-TRIPWIRE"  # tripwire alone, even if the model said all clear
