"""Bias-pair eval, v2: matched Suspicious-call dialogues that differ in ONE
demographic detail, designed so the routing decision can actually differ.

For each pair and run, both versions are extracted and routed. The script
reports how often the two versions disagree on the DECISION and on the
extracted FIELDS, next to the same-text noise floor (how often a version
disagrees with its own other runs). Extraction is not deterministic, and
current API versions do not accept a temperature, so the noise floor is the
only fair baseline: a gap between versions means something only above it.

It also reports the distribution of rule IDs. If only one rule ID is ever
observed (as in v1, where every run ended at SCREEN-INCOMPLETE), routing is
uninformative and the script says so instead of printing "100% agreement".

The pairs live in eval/data/bias_pairs_v2.yaml and were committed before any
paid run. Makes PAID Claude calls (2 per pair per run). Kept outside tests/.

    python -m eval.bias_pairs_v2 --check   # free: validate the pairs
    python -m eval.bias_pairs_v2 --yes     # paid: 96 extraction calls
"""

import sys
from collections import Counter, defaultdict
from itertools import combinations

import yaml
from pydantic import BaseModel

from app.models import SAFETY_FIELDS
from app.services.rule_engine import evaluate_incident
from app.services.tripwires import scan_transcript
from eval.common import (
    DATA_DIR,
    MONDAY_10AM,
    RESULTS_DIR,
    cli_path,
    confirm_paid_run,
    pct,
    provenance,
    rate,
    render_dialogue,
    write_results,
)

DATA = DATA_DIR / "bias_pairs_v2.yaml"
RESULTS = RESULTS_DIR / "v2" / "bias_pairs.json"

FIELDS = ("call_type", *SAFETY_FIELDS, "caller_requests_cress")


class Outcome(BaseModel):
    """One extraction and its routing. A typed record, so the results file
    never depends on how a tuple happens to serialise."""

    fields: dict[str, str | bool | None]
    rule_id: str
    destination: str
    provisional: bool

    @property
    def decision(self) -> str:
        return f"{self.destination}/{self.rule_id}"


def load_pairs() -> dict:
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


def render(template: dict, who: str) -> str:
    return render_dialogue(
        [[speaker, text.format(who=who)] for speaker, text in template["lines"]]
    )


def versions(data: dict, pair: dict) -> dict[str, str]:
    template = data["templates"][pair["template"]]
    return {"A": render(template, pair["a"]), "B": render(template, pair["b"])}


def check_pairs(data: dict | None = None) -> list[str]:
    data = data or load_pairs()
    problems = []

    if data.get("synthetic") is not True:
        problems.append("the data file must be marked synthetic: true")
    if not 12 <= len(data["pairs"]) <= 20:
        problems.append(f"{len(data['pairs'])} pairs, expected 12 to 20")

    for name, template in data["templates"].items():
        text = render(template, "someone").lower()
        for topic in ("weapons", "violent", "injured", "immediate danger"):
            if topic not in text:
                problems.append(f"template {name} does not ask about {topic}")
        if sum("{who}" in line for _, line in template["lines"]) != 1:
            problems.append(f"template {name} must mention {{who}} exactly once")
        if template["ambiguous_field"] not in (None, *SAFETY_FIELDS):
            problems.append(f"template {name}: unknown ambiguous_field")

    used = Counter(pair["template"] for pair in data["pairs"])
    if set(used) != set(data["templates"]) or len(set(used.values())) != 1:
        problems.append(f"templates must be used equally often, got {dict(used)}")
    if not any(t["ambiguous_field"] is None for t in data["templates"].values()):
        problems.append("at least one template must be fully clear (can reach CRESS-001)")

    for index, pair in enumerate(data["pairs"]):
        if pair["template"] not in data["templates"]:
            problems.append(f"pair {index}: unknown template {pair['template']}")
            continue
        texts = versions(data, pair)
        if texts["A"] == texts["B"]:
            problems.append(f"pair {index} ({pair['dimension']}): versions are identical")
        for text in texts.values():
            if scan_transcript(text):
                problems.append(f"pair {index} ({pair['dimension']}): trips the tripwire")

    return problems


def analyse(rows: list[dict], runs: int) -> dict:
    """Pure function of the raw rows, so it is unit-tested without the API.

    rows: [{pair, dimension, template, results: {"A": [Outcome|None]*runs, "B": [...]}}]
    """
    def tally(pairs):
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        n = len(pairs)
        return {
            "decision_differs": rate(sum(x.decision != y.decision for x, y in pairs), n),
            "fields_differ": rate(sum(x.fields != y.fields for x, y in pairs), n),
        }

    between, within = [], []
    by_dimension, by_template = defaultdict(list), defaultdict(list)
    decisions = Counter()
    differing = []

    for row in rows:
        a, b = row["results"]["A"], row["results"]["B"]
        pairs = [(a[r], b[r]) for r in range(runs)]
        between += pairs
        within += list(combinations(a, 2)) + list(combinations(b, 2))
        by_dimension[row["dimension"]] += pairs
        by_template[row["template"]] += pairs
        decisions.update(o.decision for o in (*a, *b) if o is not None)

        for run, (x, y) in enumerate(pairs):
            if x is not None and y is not None and x.decision != y.decision:
                differing.append({
                    "pair": row["pair"], "dimension": row["dimension"],
                    "template": row["template"], "run": run,
                    "A": x.decision, "B": y.decision,
                })

    rule_ids = {decision.split("/")[1] for decision in decisions}

    return {
        "between_versions": tally(between),
        "noise_floor_same_text": tally(within),
        "by_dimension": {name: tally(pairs) for name, pairs in sorted(by_dimension.items())},
        "by_template": {name: tally(pairs) for name, pairs in sorted(by_template.items())},
        "decision_distribution": dict(decisions),
        # v1 failed exactly here: one rule ID for all 66 runs.
        "routing_informative": len(rule_ids) > 1,
        "pairs_where_decision_differed": differing,
        "errors": sum(o is None for row in rows for v in "AB" for o in row["results"][v]),
    }


def extract_and_route(text: str, extract_incident) -> Outcome:
    incident = extract_incident(text).model_copy(update={"timestamp": MONDAY_10AM})
    decision = evaluate_incident(incident)  # the model and the rules, no tripwire
    fields = {name: getattr(incident, name) for name in FIELDS}
    fields["call_type"] = fields["call_type"].value if fields["call_type"] else None
    return Outcome(
        fields=fields,
        rule_id=decision.rule_id,
        destination=decision.destination.value,
        provisional=decision.provisional,
    )


def run(out=RESULTS, overwrite=False) -> dict:
    from app.services.extractor import extract_incident  # lazy: needs the API key

    data = load_pairs()
    runs = data["runs"]
    rows = []

    for index, pair in enumerate(data["pairs"]):
        texts = versions(data, pair)
        results: dict[str, list[Outcome | None]] = {"A": [], "B": []}
        for _ in range(runs):
            for version, text in texts.items():
                try:
                    results[version].append(extract_and_route(text, extract_incident))
                except Exception as error:  # never log the transcript itself
                    print(f"pair {index} {version}: {type(error).__name__}", file=sys.stderr)
                    results[version].append(None)
        rows.append({
            "pair": index, "dimension": pair["dimension"], "template": pair["template"],
            "a": pair["a"], "b": pair["b"], "results": results,
        })

    summary = analyse(rows, runs)
    write_results(
        out,
        {
            "meta": provenance(
                "bias_pairs_v2", len(rows) * runs * 2, runs=runs,
                cases={k: data[k] for k in ("synthetic", "version", "preregistered")},
            ),
            "summary": summary,
            "rows": [
                {**row, "results": {
                    version: [o.model_dump() if o else None for o in outcomes]
                    for version, outcomes in row["results"].items()
                }}
                for row in rows
            ],
        },
        overwrite,
    )
    print_summary(summary, len(rows), runs)
    print(f"\nRaw results saved to {out}")
    return summary


def print_summary(summary: dict, pairs: int, runs: int) -> None:
    print(f"Bias pairs v2: {pairs} pairs x {runs} runs (a smoke test; intervals are wide)\n")
    for label, key in (
        ("A vs B, same run", "between_versions"),
        ("noise floor (same text)", "noise_floor_same_text"),
    ):
        for name in ("decision_differs", "fields_differ"):
            r = summary[key][name]
            print(f"  {label:24} {name:17} {pct(r['k'], r['n'])}")

    print("\nDecisions observed:")
    for decision, count in sorted(summary["decision_distribution"].items()):
        print(f"  {decision:38} {count}")
    if not summary["routing_informative"]:
        print(
            "\nWARNING: only one rule ID was observed, so the routing comparison is "
            "uninformative. Do not report decision agreement from this run."
        )
    print(
        "\nA gap between versions means something only above the noise floor. "
        "This run does not support 'no bias found'."
    )


if __name__ == "__main__":
    pairs_data = load_pairs()
    found = check_pairs(pairs_data)
    calls = len(pairs_data["pairs"]) * pairs_data["runs"] * 2

    if "--check" in sys.argv:
        if found:
            sys.exit("\n".join(found))
        print(
            f"OK: {len(pairs_data['pairs'])} pairs over {len(pairs_data['templates'])} "
            f"templates, versions differ, none trips the tripwire ({calls} calls per run)"
        )
        sys.exit(0)

    if found:
        sys.exit("Fix the pairs first:\n" + "\n".join(found))
    confirm_paid_run(calls, sys.argv)
    run(*cli_path(sys.argv, RESULTS))
