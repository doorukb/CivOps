"""Shared pieces of the paid evaluations: statistics, provenance, result files.

Nothing here calls the API. The paid step is `extract` in each eval's run().
"""

import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RESULTS_DIR = Path(__file__).parent / "results"
DATA_DIR = Path(__file__).parent / "data"

# Every case is evaluated as if it arrived Monday 10 AM local time, when CRESS
# is on duty, so a fully cleared eligible call can reach CRESS-001.
MONDAY_10AM = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("America/New_York"))

AWAY_FROM_HUMAN = ("cress", "cress_followup")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes out of n."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> dict:
    """A count with its share and Wilson 95% interval, ready for a results file."""
    low, high = wilson(k, n)
    return {
        "k": k,
        "n": n,
        "share": round(k / n, 4) if n else None,
        "wilson95": [round(low, 4), round(high, 4)],
    }


def pct(k: int, n: int) -> str:
    if n == 0:
        return "0/0"
    low, high = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%}  (Wilson 95% CI {low:.0%} to {high:.0%})"


def git_sha() -> str | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True, text=True, check=True, cwd=Path(__file__).parent,
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def provenance(eval_name: str, n: int, **extra) -> dict:
    """Who produced a result: recorded in every results file so a number can
    always be traced to a model, a prompt and a commit."""
    from app.rulebook import load_rulebook
    from app.services.extractor import extraction_model, prompt_sha256

    return {
        "eval": eval_name,
        "run_date": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": extraction_model(),
        "extractor_prompt_sha256": prompt_sha256(),
        "rulebook_version": load_rulebook().version,
        "git_sha": git_sha(),
        # Current API versions reject sampling parameters, so temperature
        # cannot be pinned to 0. The same-text noise floor is reported instead.
        "temperature": "not settable (API default)",
        "n": n,
        "synthetic": True,
        **extra,
    }


def write_results(path: Path, payload: dict, overwrite: bool = False) -> Path:
    """Write a results file. Refuses to replace an existing one: results are
    history. Pass overwrite=True (the --overwrite flag) to do it on purpose."""
    if path.exists() and not overwrite:
        sys.exit(
            f"{path} already exists. Results are kept as history.\n"
            "Pass --out PATH to write this run elsewhere, or --overwrite to replace it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def cli_path(argv: list[str], default: Path) -> tuple[Path, bool]:
    """Parse the two flags every eval shares: --out PATH and --overwrite."""
    out = default
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
    return out, "--overwrite" in argv


def confirm_paid_run(calls: int, argv: list[str]) -> None:
    """A paid run must be asked for by name, never started by accident."""
    if "--yes" in argv:
        return
    sys.exit(
        f"This makes {calls} paid Claude extraction calls.\n"
        "Run the free check first (--check), then repeat with --yes to spend."
    )


def render_dialogue(lines: list[dict] | list[list[str]]) -> str:
    """[[speaker, text], ...] -> the 'Dispatcher: ...' / 'Caller: ...' text the
    console builds from transcript events."""
    return "\n".join(f"{speaker.title()}: {text}" for speaker, text in lines)
