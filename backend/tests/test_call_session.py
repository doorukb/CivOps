import asyncio

import pytest

from app.services.call_session import (
    CALL_ENDED,
    CALL_STARTED,
    SCENARIOS,
    play_scenario,
    system_event,
)
from app.services.tripwires import scan_transcript

HIDDEN = "hidden_knife"


def test_system_event_is_final_system_marker():
    event = system_event(CALL_ENDED)
    assert (event.speaker, event.text, event.is_final) == ("system", CALL_ENDED, True)


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_only_hidden_emergency_has_tripwire_word(scenario_id):
    text = " ".join(line for _, line in SCENARIOS[scenario_id].lines)
    assert bool(scan_transcript(text)) == (scenario_id == HIDDEN)


def test_routine_script_asks_all_four_questions():
    asked = " ".join(
        t for s, t in SCENARIOS["routine_wellbeing"].lines if s == "dispatcher"
    ).lower()
    for topic in ("weapons", "violent", "injured", "immediate danger"):
        assert topic in asked


def test_routine_answers_are_full_sentences():
    caller = [t for s, t in SCENARIOS["routine_wellbeing"].lines if s == "caller"]
    assert sum(t.startswith("No, ") and len(t.split()) > 3 for t in caller) == 4
    assert all(t.strip(" .!").lower() != "no" for t in caller)


def run(scenario_id, speed=1e6, cancel_after=None):
    events = []

    async def broadcast(event):
        events.append(event)

    async def go():
        task = asyncio.create_task(play_scenario(scenario_id, broadcast, speed))
        if cancel_after is None:
            return await task
        await asyncio.sleep(cancel_after)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    return events


def test_each_line_is_partial_then_final_between_markers():
    events = run(HIDDEN)
    lines = SCENARIOS[HIDDEN].lines

    assert events[0].text == CALL_STARTED
    assert events[-1].text == CALL_ENDED
    body = events[1:-1]
    assert len(body) == 2 * len(lines)
    for (speaker, text), partial, final in zip(lines, body[::2], body[1::2], strict=True):
        assert not partial.is_final and final.is_final
        assert final.text == text and final.speaker == partial.speaker == speaker
        assert len(partial.text.split()) <= len(text.split()) // 2 or len(text.split()) == 1


def test_cancellation_still_sends_ended():
    events = run("routine_wellbeing", speed=1.0, cancel_after=0.05)
    assert events[-1].text == CALL_ENDED
    assert len(events) < 2 * len(SCENARIOS["routine_wellbeing"].lines)
