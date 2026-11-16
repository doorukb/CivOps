"""Extraction accuracy: per-field accuracy of the extraction pipeline on 40
hand-labelled synthetic calls.

What is scored is the pipeline's output (model, then evidence check, then hedge
check), because that is what the rulebook receives. Besides per-field accuracy
with Wilson 95% intervals, it reports the two error types that matter for
safety separately:

* MISSED CONCERN: gold is true, the pipeline returned false or unknown.
* UNKNOWN TREATED AS NO: gold is unknown, the pipeline returned false. This is
  the error that can send an unscreened call to CRESS.

The opposite errors (false -> unknown, anything -> true) only cost a human
look; they are counted as over-caution.

Cases and labels live in eval/data/extraction_gold.yaml and were committed
before any paid run. Makes PAID Claude calls (one per case). Outside tests/.

    python -m eval.extraction_accuracy --check   # free: validate cases and labels
    python -m eval.extraction_accuracy --yes     # paid: 40 extraction calls
"""

import sys
from collections import Counter, defaultdict

import yaml

from app.models import SAFETY_FIELDS, CallType
from eval.common import (
    DATA_DIR,
    RESULTS_DIR,
    cli_path,
    confirm_paid_run,
    pct,
    provenance,
    rate,
    render_dialogue,
    write_results,
)

DATA = DATA_DIR / "extraction_gold.yaml"
RESULTS = RESULTS_DIR / "v2" / "extraction_accuracy.json"

FIELDS = ("call_type", *SAFETY_FIELDS, "caller_requests_cress")
CATEGORIES = ("plain", "hedge", "question", "positive", "unlabelled", "partial", "request")
CALL_TYPES = {None, *(t.value for t in CallType)}


def load_cases() -> dict:
    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    for case in data["cases"]:
        case["text"] = render_dialogue(case["lines"]) if "lines" in case else case["text"]
    return data


def acceptable(gold) -> list:
    """Gold labels as a list: call_type may list several acceptable labels."""
    return gold if isinstance(gold, list) else [gold]


def check_cases(data: dict | None = None) -> list[str]:
    data = data or load_cases()
    cases = data["cases"]
    problems = []

    if data.get("synthetic") is not True:
        problems.append("the data file must be marked synthetic: true")
    if not 30 <= len(cases) <= 60:
        problems.append(f"{len(cases)} cases, expected 30 to 60")

    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        problems.append("duplicate case ids")

    for case in cases:
        gold = case["gold"]
        if case["category"] not in CATEGORIES:
            problems.append(f"{case['id']}: unknown category {case['category']}")
        if set(gold) != set(FIELDS):
            problems.append(f"{case['id']}: gold must label exactly {FIELDS}")
            continue
        if not set(acceptable(gold["call_type"])) <= CALL_TYPES:
            problems.append(f"{case['id']}: unknown call_type in gold")
        for field in FIELDS[1:]:
            if gold[field] not in (True, False, None):
                problems.append(f"{case['id']}: {field} must be true, false or null")

    # The set has to exercise every answer for every screening field, and
    # every category, or an accuracy number hides a blind spot.
    for field in SAFETY_FIELDS:
        seen = {case["gold"][field] for case in cases}
        if seen != {True, False, None}:
            problems.append(f"{field}: gold never takes the value(s) {({True, False, None} - seen)}")
    missing = set(CATEGORIES) - {case["category"] for case in cases}
    if missing:
        problems.append(f"no cases in categories {sorted(missing)}")

    return problems


def error_kind(gold, predicted) -> str | None:
    """Classify a wrong screening answer by what it would cost."""
    if predicted == gold:
        return None
    if gold is True:
        return "missed_concern"            # true -> false / unknown
    if gold is None and predicted is False:
        return "unknown_treated_as_no"     # the dangerous direction
    return "over_caution"                  # false -> unknown, or anything -> true


def score(rows: list[dict]) -> dict:
    """Pure function of the per-case rows, so it is unit-tested without the API.

    rows: [{id, category, gold: {...}, predicted: {...}, downgraded: [...]}]
    """
    ok = [r for r in rows if "error" not in r]
    n = len(ok)

    def correct(row, field) -> bool:
        return row["predicted"][field] in acceptable(row["gold"][field])

    per_field = {f: rate(sum(correct(r, f) for r in ok), n) for f in FIELDS}

    confusion = {
        field: {
            f"{gold}->{predicted}": count
            for (gold, predicted), count in sorted(
                Counter((r["gold"][field], r["predicted"][field]) for r in ok).items(),
                key=str,
            )
        }
        for field in SAFETY_FIELDS
    }

    kinds = Counter()
    examples = defaultdict(list)
    for row in ok:
        for field in SAFETY_FIELDS:
            kind = error_kind(row["gold"][field], row["predicted"][field])
            if kind:
                kinds[kind] += 1
                examples[kind].append(f"{row['id']}.{field}")

    answers = n * len(SAFETY_FIELDS)
    gold_true = sum(r["gold"][f] is True for r in ok for f in SAFETY_FIELDS)
    gold_unknown = sum(r["gold"][f] is None for r in ok for f in SAFETY_FIELDS)

    by_category = {}
    for category in CATEGORIES:
        subset = [r for r in ok if r["category"] == category]
        by_category[category] = rate(
            sum(correct(r, f) for r in subset for f in SAFETY_FIELDS),
            len(subset) * len(SAFETY_FIELDS),
        )

    return {
        "n": n,
        "errors": len(rows) - n,
        "per_field_accuracy": per_field,
        "all_six_fields_correct": rate(sum(all(correct(r, f) for f in FIELDS) for r in ok), n),
        "screening_answers": {
            "accuracy": rate(sum(correct(r, f) for r in ok for f in SAFETY_FIELDS), answers),
            # The two that matter for safety, each against the cases where it can occur.
            "missed_concern": rate(kinds["missed_concern"], gold_true),
            "unknown_treated_as_no": rate(kinds["unknown_treated_as_no"], gold_unknown),
            "over_caution": rate(kinds["over_caution"], answers),
        },
        "error_examples": {kind: sorted(ids) for kind, ids in examples.items()},
        "confusion": confusion,
        "screening_accuracy_by_category": by_category,
        # How often the deterministic checks changed the model's answer.
        "answers_reset_by_post_checks": sum(len(r.get("downgraded", [])) for r in ok),
    }


def run(out=RESULTS, overwrite=False) -> dict:
    from app.services.extractor import extract_incident  # lazy: needs the API key

    data = load_cases()
    rows = []

    for case in data["cases"]:
        row = {"id": case["id"], "category": case["category"], "gold": case["gold"]}
        try:
            result = extract_incident(case["text"])
        except Exception as error:  # never log the transcript itself
            rows.append({**row, "error": type(error).__name__})
            continue

        predicted = {field: getattr(result, field) for field in FIELDS}
        predicted["call_type"] = predicted["call_type"].value if predicted["call_type"] else None
        rows.append({
            **row,
            "predicted": predicted,
            "downgraded": sorted(result.downgraded),
            "warnings": result.warnings,
        })

    summary = score(rows)
    write_results(
        out,
        {
            "meta": provenance(
                "extraction_accuracy", len(rows),
                cases={k: data[k] for k in ("synthetic", "version", "preregistered")},
            ),
            "summary": summary,
            "rows": rows,
        },
        overwrite,
    )
    print_summary(summary)
    print(f"\nPer-case results saved to {out}")
    return summary


def print_summary(summary: dict) -> None:
    def line(label: str, r: dict) -> None:
        print(f"  {label:28} {pct(r['k'], r['n'])}")

    print(f"Extraction accuracy on {summary['n']} synthetic calls (small n; intervals are wide)\n")
    for field, result in summary["per_field_accuracy"].items():
        line(field, result)
    line("all six fields correct", summary["all_six_fields_correct"])

    s = summary["screening_answers"]
    print("\nScreening answers, by what an error costs:")
    line("MISSED CONCERN (true lost)", s["missed_concern"])
    line("UNKNOWN TREATED AS NO", s["unknown_treated_as_no"])
    line("over-caution", s["over_caution"])
    print(f"\n{summary['answers_reset_by_post_checks']} answers were reset by the evidence/hedge checks")
    print(f"{summary['errors']} failed calls excluded")


if __name__ == "__main__":
    gold_data = load_cases()
    found = check_cases(gold_data)

    if "--check" in sys.argv:
        if found:
            sys.exit("\n".join(found))
        categories = Counter(case["category"] for case in gold_data["cases"])
        print(f"OK: {len(gold_data['cases'])} labelled cases: {dict(categories)}")
        sys.exit(0)

    if found:
        sys.exit("Fix the cases first:\n" + "\n".join(found))
    confirm_paid_run(len(gold_data["cases"]), sys.argv)
    run(*cli_path(sys.argv, RESULTS))
