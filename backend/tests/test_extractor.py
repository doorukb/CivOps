from types import SimpleNamespace

import pytest

import app.services.extractor as extractor
from app.services.extractor import ExtractedIncident

TRANSCRIPT = (
    "Dispatcher: Is anyone hurt?\n"
    "Caller: No,   nobody is hurt.\n"
    "Caller: He’s just yelling at the wall."
)

SAFETY = ("weapon_present", "violence", "injury", "immediate_danger")


def fake_extract(monkeypatch, transcript=TRANSCRIPT, **findings):
    """Run extract_incident against a fake client that returns `findings`."""
    canned = ExtractedIncident(
        call_type="wellbeing_check",
        caller_requests_cress=None,
        **{f: findings.get(f, {"value": None, "evidence": None}) for f in SAFETY},
    )
    calls = []

    class FakeMessages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(parsed_output=canned)

    monkeypatch.setattr(
        extractor, "Anthropic", lambda **_: SimpleNamespace(messages=FakeMessages())
    )
    return extractor.extract_incident(transcript), calls


def test_supported_evidence_is_kept(monkeypatch):
    incident, calls = fake_extract(
        monkeypatch, injury={"value": False, "evidence": "nobody is hurt"}
    )
    assert incident.injury is False
    assert incident.evidence == {"injury": "nobody is hurt"}
    assert len(calls) == 1


def test_invented_evidence_is_downgraded(monkeypatch):
    incident, _ = fake_extract(
        monkeypatch, weapon_present={"value": False, "evidence": "no weapons here"}
    )
    assert incident.weapon_present is None
    assert incident.evidence == {}


def test_value_without_evidence_is_downgraded(monkeypatch):
    incident, _ = fake_extract(
        monkeypatch, violence={"value": True, "evidence": None}
    )
    assert incident.violence is None


def test_blank_evidence_is_downgraded(monkeypatch):
    incident, _ = fake_extract(
        monkeypatch, injury={"value": False, "evidence": "   "}
    )
    assert incident.injury is None


def test_empty_transcript_never_calls_the_api(monkeypatch):
    with pytest.raises(ValueError):
        fake_extract(monkeypatch, transcript="  \n ")


def test_quote_with_speaker_label_dropped_is_accepted(monkeypatch):
    # Spans two lines; the model left out "Caller:" in between.
    incident, _ = fake_extract(
        monkeypatch,
        injury={"value": False, "evidence": "Is anyone hurt? No, nobody is hurt."},
    )
    assert incident.injury is False


def test_quote_joining_question_and_labelled_answer_is_accepted(monkeypatch):
    # One line in the quote, two lines in the transcript, with "Caller:" kept.
    incident, _ = fake_extract(
        monkeypatch,
        injury={"value": False, "evidence": "Is anyone hurt? Caller: No, nobody is hurt."},
    )
    assert incident.injury is False


@pytest.mark.parametrize(
    "quote", ["NOBODY IS HURT", "no, nobody is hurt", "he's just yelling"]
)
def test_whitespace_case_or_apostrophe_different_quote_is_accepted(monkeypatch, quote):
    incident, _ = fake_extract(
        monkeypatch, immediate_danger={"value": False, "evidence": quote}
    )
    assert incident.immediate_danger is False
