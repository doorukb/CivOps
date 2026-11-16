"""Record what the real extractor returns for the three scripted demo calls.

The result (eval/fixtures/demo_scripts.json) is the model's RAW proposal for
each script, before the deterministic checks. tests/test_demo_fixtures.py
replays it offline through the checks and the rulebook, so the demo's
behaviour is regression-tested on every commit without paid calls.

Until this has been run, the fixture holds a hand-written ideal extraction and
says so (`"recorded": false`).

    python -m eval.record_demo_fixtures --yes     # paid: 3 extraction calls
"""

import json
import sys
from pathlib import Path

from app.services.call_session import SCENARIOS
from eval.common import confirm_paid_run, provenance, render_dialogue

FIXTURE = Path(__file__).parent / "fixtures" / "demo_scripts.json"


def transcript_of(scenario_id: str) -> str:
    """The transcript exactly as the console builds it from the events."""
    return render_dialogue([list(line) for line in SCENARIOS[scenario_id].lines])


def record() -> None:
    from app.services.extractor import propose  # lazy: needs the API key

    scripts = {}
    for scenario_id in SCENARIOS:
        proposal = propose(transcript_of(scenario_id))
        if isinstance(proposal, str):
            sys.exit(f"{scenario_id}: {proposal} Nothing was written.")
        scripts[scenario_id] = {"model_output": proposal.model_dump(mode="json")}

    FIXTURE.write_text(
        json.dumps(
            {
                "recorded": True,
                "meta": provenance("demo_script_fixtures", len(scripts)),
                "scripts": scripts,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded {len(scripts)} scripts to {FIXTURE}. Now run: python -m pytest tests/test_demo_fixtures.py")


if __name__ == "__main__":
    confirm_paid_run(len(SCENARIOS), sys.argv)
    record()
