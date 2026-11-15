import pytest
from pydantic import ValidationError

from app.models import TranscriptEvent


def test_transcript_event():
    event = TranscriptEvent(
        speaker="caller",
        text="My neighbor is yelling.",
        is_final=True,
        t=12.4
    )

    assert event.speaker == "caller"
    assert event.is_final is True
    assert event.t == 12.4


def test_negative_timestamp():
    with pytest.raises(ValidationError):
        TranscriptEvent(
            speaker="caller",
            text="Hello",
            is_final=True,
            t=-5
        )