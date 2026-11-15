import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.models import TranscriptEvent

logger = logging.getLogger(__name__)

CALL_STARTED = "__call_started__"
CALL_ENDED = "__call_ended__"
CALL_ERROR = "__call_error__"


def system_event(marker: str) -> TranscriptEvent:
    return TranscriptEvent(speaker="system", text=marker, is_final=True, t=0.0)


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    summary: str
    lines: tuple[tuple[str, str], ...]  # (speaker, text)


_INTRO = ("dispatcher", "This call is a simulation and is being recorded. How can I help?")

SCENARIOS = {
    s.id: s
    for s in (
        Scenario(
            "routine_wellbeing",
            "Routine wellbeing check",
            "A caller worries about a neighbor unseen for three days; all screening answers are clear.",
            (
                _INTRO,
                ("caller", "I'm worried about my neighbor, an older man who lives alone."),
                ("caller", "I haven't seen him come out for his mail in three days."),
                ("dispatcher", "I'll ask a few quick questions. Are there any weapons involved?"),
                ("caller", "No, there are no weapons."),
                ("dispatcher", "Has anyone been violent or threatened anyone?"),
                ("caller", "No, nobody has been violent and nobody has threatened anyone."),
                ("dispatcher", "Is anyone injured?"),
                ("caller", "No, nobody is injured."),
                ("dispatcher", "Is anyone in immediate danger?"),
                ("caller", "No, nobody is in immediate danger."),
                ("caller", "Could you send community responders to knock on his door and check on him?"),
            ),
        ),
        Scenario(
            "incomplete_screening",
            "Argument with unknown safety details",
            "Two neighbors argue loudly; only the injury question gets an answer.",
            (
                _INTRO,
                ("caller", "Two of my neighbors are arguing really loudly in the hallway."),
                ("dispatcher", "Are there any weapons involved?"),
                ("caller", "Sorry, I can't hear you over all the shouting."),
                ("dispatcher", "Has anyone been violent or threatened anyone?"),
                ("caller", "They just keep going at it, it's so loud out here."),
                ("dispatcher", "Is anyone injured?"),
                ("caller", "Nobody is injured, I can see both of them from my door."),
                ("dispatcher", "Is anyone in immediate danger?"),
                ("caller", "Hold on, they're yelling again and I lost your question."),
            ),
        ),
        Scenario(
            "hidden_knife",
            "Noise complaint, then a hidden emergency",
            "Starts as a noise complaint; the caller then hears a man yell that he has a knife.",
            (
                _INTRO,
                ("caller", "My upstairs neighbors are being really loud again."),
                ("dispatcher", "Can you tell me what you are hearing?"),
                ("caller", "Shouting and doors slamming, it has gone on for an hour."),
                ("caller", "Wait, I just heard a man yell that he has a knife!"),
            ),
        ),
    )
}


async def play_scenario(
    scenario_id: str,
    broadcast: Callable[[TranscriptEvent], Awaitable[object]],
    speed: float = 1.0,
) -> None:
    scenario = SCENARIOS[scenario_id]  # KeyError before STARTED: nothing to close
    t = 0.0
    marker = CALL_ENDED

    await broadcast(system_event(CALL_STARTED))
    try:
        for speaker, text in scenario.lines:
            words = text.split()
            partial = " ".join(words[: max(1, len(words) // 2)])
            await broadcast(
                TranscriptEvent(speaker=speaker, text=partial, is_final=False, t=t)
            )

            pause = max(1.2, 0.28 * len(words)) / speed
            await asyncio.sleep(pause)
            t += pause

            await broadcast(
                TranscriptEvent(speaker=speaker, text=text, is_final=True, t=t)
            )
    except Exception:
        # Runs as a background task: log here, the page gets ERROR.
        marker = CALL_ERROR
        logger.exception("Scripted call failed")
    finally:
        # Runs on cancellation too, so End Call still closes cleanly.
        await broadcast(system_event(marker))
