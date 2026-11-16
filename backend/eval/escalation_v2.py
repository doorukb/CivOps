"""Escalation eval, v2: disguised emergencies AND benign controls.

Reports two rates side by side, each with a Wilson 95% interval:

* on emergencies, how many the model recognised (SAFETY-ESCALATION), how many
  reached a human only because screening was incomplete, and how many were
  routed to CRESS (missed);
* on fully screened benign calls, how many were wrongly escalated for safety
  (false escalation), how many were left incomplete, and how many were cleared.

The cases live in eval/data/escalation_v2.yaml and were committed before any
paid run. Makes PAID Claude calls (one per case). Kept outside tests/.

    python -m eval.escalation_v2 --check   # free: validate the cases, run the tripwire
    python -m eval.escalation_v2 --yes     # paid: 70 extraction calls
"""

import sys
from collections import Counter

import yaml

from app.models import Destination
from app.services.rule_engine import evaluate_incident
from app.services.tripwires import scan_transcript
from eval.common import (
    AWAY_FROM_HUMAN,
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
from eval.missed_escalations import CASES as V1_EMERGENCIES

DATA = DATA_DIR / "escalation_v2.yaml"
RESULTS = RESULTS_DIR / "v2" / "escalation.json"

GROUPS = ("emergencies", "controls", "paragraph_controls", "hard_negatives")


def load_cases() -> dict[str, list[dict]]:
    """Every case as {id, group, form, text, expect?}. The 27 v1 emergencies
    are reused from their own module so they cannot drift from the archive."""
    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))

    def case(group: str, entry: dict) -> dict:
        dialogue = "lines" in entry
        return {
            "id": entry["id"],
            "group": group,
            "form": "dialogue" if dialogue else "paragraph",
            "text": render_dialogue(entry["lines"]) if dialogue else entry["text"],
            "expect": entry.get("expect"),
        }

    cases = {
        "emergencies": [
            {"id": f"v1_{case_id}", "group": "emergencies", "form": "paragraph",
             "text": text, "expect": None}
            for case_id, text in V1_EMERGENCIES
        ] + [case("emergencies", entry) for entry in data["emergencies"]],
    }
    for group in GROUPS[1:]:
        cases[group] = [case(group, entry) for entry in data[group]]

    cases["_meta"] = {key: data[key] for key in ("synthetic", "version", "preregistered")}
    return cases


def check_cases(cases: dict | None = None) -> list[str]:
    """Free validation: returns problems (empty means fine)."""
    cases = cases or load_cases()
    problems = []

    if cases["_meta"]["synthetic"] is not True:
        problems.append("the data file must be marked synthetic: true")

    ids = [c["id"] for group in GROUPS for c in cases[group]]
    if len(set(ids)) != len(ids):
        problems.append("duplicate case ids")

    sizes = {group: len(cases[group]) for group in GROUPS}
    if sizes["emergencies"] != 40:
        problems.append(f"{sizes['emergencies']} emergencies, expected 40")
    if not 15 <= sizes["controls"] <= 30:
        problems.append(f"{sizes['controls']} controls, expected 15 to 30")

    # The premise: emergencies are not caught by the keyword list.
    for c in cases["emergencies"]:
        flags = scan_transcript(c["text"])
        if flags:
            problems.append(f"{c['id']} trips the tripwire: {flags}")

    # A control has to be fully screened to count as a control.
    for c in cases["controls"]:
        lowered = c["text"].lower()
        for topic in ("weapons", "violent", "injured", "immediate danger"):
            if "dispatcher: " not in lowered or topic not in lowered:
                problems.append(f"{c['id']} does not ask about {topic}")
        if c["expect"] not in ("CRESS-001", "REVIEW-001"):
            problems.append(f"{c['id']} needs expect: CRESS-001 or REVIEW-001")

    # Hard negatives exist to trip the keyword list; one that does not is mislabelled.
    for c in cases["hard_negatives"]:
        if not scan_transcript(c["text"]):
            problems.append(f"{c['id']} is a hard negative but does not trip the tripwire")

    return problems


def tripwire_report(cases: dict) -> dict:
    """Free and deterministic: how often the keyword list fires on each group."""
    return {
        group: rate(sum(bool(scan_transcript(c["text"])) for c in cases[group]), len(cases[group]))
        for group in GROUPS
    }


def bucket(rule_id: str, destination: Destination) -> str:
    """Where the model and the rules (without the tripwire) sent a case."""
    if rule_id == "SAFETY-ESCALATION":
        return "safety_escalation"
    if rule_id == "SCREEN-INCOMPLETE":
        return "incomplete_screening"
    if destination.value in AWAY_FROM_HUMAN:
        return "to_cress"
    return "other_review"  # e.g. REVIEW-001: the call type is not eligible


def summarize(rows: list[dict]) -> dict:
    """Pure function of the per-case rows, so it is unit-tested without the API."""
    ok = [r for r in rows if "error" not in r]

    def group(name: str) -> list[dict]:
        return [r for r in ok if r["group"] == name]

    def count(items: list[dict], *buckets: str) -> int:
        return sum(r["bucket"] in buckets for r in items)

    emergencies, controls = group("emergencies"), group("controls")
    paragraphs, hard = group("paragraph_controls"), group("hard_negatives")
    dialogues = [r for r in emergencies if r["form"] == "dialogue"]

    return {
        "errors": len(rows) - len(ok),
        "emergencies": {
            "n": len(emergencies),
            "buckets": dict(Counter(r["bucket"] for r in emergencies)),
            # Headline: the model recognised the danger.
            "recognised": rate(count(emergencies, "safety_escalation"), len(emergencies)),
            # Weak catch: reached a human only because a question was unanswered.
            "incomplete_only": rate(count(emergencies, "incomplete_screening"), len(emergencies)),
            "other_review": rate(count(emergencies, "other_review"), len(emergencies)),
            "missed": rate(count(emergencies, "to_cress"), len(emergencies)),
            # The screened dialogues are the cases where a miss is possible.
            "screened_dialogues": {
                "recognised": rate(count(dialogues, "safety_escalation"), len(dialogues)),
                "missed": rate(count(dialogues, "to_cress"), len(dialogues)),
            },
            # A CRESS recommendation built on model-only "no" answers is
            # provisional in the console until a person confirms them.
            "missed_but_provisional": sum(
                r["bucket"] == "to_cress" and r["provisional"] for r in emergencies
            ),
        },
        "controls": {
            "n": len(controls),
            "buckets": dict(Counter(r["bucket"] for r in controls)),
            "false_escalation": rate(count(controls, "safety_escalation"), len(controls)),
            "left_incomplete": rate(count(controls, "incomplete_screening"), len(controls)),
            "reached_expected_rule": rate(
                sum(r["rule_id"] == r["expect"] for r in controls), len(controls)
            ),
        },
        "paragraph_controls": {
            "n": len(paragraphs),
            "buckets": dict(Counter(r["bucket"] for r in paragraphs)),
            "false_escalation": rate(count(paragraphs, "safety_escalation"), len(paragraphs)),
            "incomplete_as_expected": rate(
                count(paragraphs, "incomplete_screening"), len(paragraphs)
            ),
        },
        "hard_negatives": {
            "n": len(hard),
            "tripwire_flagged": rate(sum(r["tripwire"] for r in hard), len(hard)),
        },
    }


def run(out=RESULTS, overwrite=False) -> dict:
    from app.services.extractor import extract_incident  # lazy: needs the API key

    cases = load_cases()
    rows = []

    for group in GROUPS:
        for c in cases[group]:
            row = {k: c[k] for k in ("id", "group", "form", "expect")}
            row["tripwire"] = bool(scan_transcript(c["text"]))
            try:
                incident = extract_incident(c["text"]).model_copy(
                    update={"timestamp": MONDAY_10AM}
                )
            except Exception as error:  # never log the transcript itself
                rows.append({**row, "error": type(error).__name__})
                continue

            # The model and the rules alone, without the transcript tripwire.
            decision = evaluate_incident(incident)
            rows.append({
                **row,
                "call_type": incident.call_type.value if incident.call_type else None,
                "weapon_present": incident.weapon_present,
                "violence": incident.violence,
                "injury": incident.injury,
                "immediate_danger": incident.immediate_danger,
                "downgraded": sorted(incident.downgraded),
                "warnings": incident.warnings,
                "rule_id": decision.rule_id,
                "destination": decision.destination.value,
                "provisional": decision.provisional,
                "bucket": bucket(decision.rule_id, decision.destination),
            })

    summary = summarize(rows)
    write_results(
        out,
        {
            "meta": provenance(
                "escalation_v2", len(rows), cases=cases["_meta"],
                tripwire=tripwire_report(cases),
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
        print(f"  {label:34} {pct(r['k'], r['n'])}")

    e, c = summary["emergencies"], summary["controls"]
    print(f"Disguised emergencies (n = {e['n']}; small, intervals are wide)")
    line("recognised (SAFETY-ESCALATION)", e["recognised"])
    line("incomplete screening only", e["incomplete_only"])
    line("other human review", e["other_review"])
    line("MISSED (routed to CRESS)", e["missed"])
    line("  of the screened dialogues", e["screened_dialogues"]["missed"])
    print(f"\nFully screened benign controls (n = {c['n']})")
    line("FALSE ESCALATION (safety)", c["false_escalation"])
    line("left incomplete", c["left_incomplete"])
    line("reached the expected rule", c["reached_expected_rule"])
    p = summary["paragraph_controls"]
    print(f"\nUnscreened benign paragraphs (n = {p['n']})")
    line("incomplete (as expected)", p["incomplete_as_expected"])
    line("false escalation (safety)", p["false_escalation"])
    print(f"\n{summary['errors']} failed calls excluded")


if __name__ == "__main__":
    all_cases = load_cases()
    found = check_cases(all_cases)
    total = sum(len(all_cases[group]) for group in GROUPS)

    if "--check" in sys.argv:
        if found:
            sys.exit("\n".join(found))
        print(f"OK: {total} cases ({', '.join(f'{len(all_cases[g])} {g}' for g in GROUPS)})")
        print("Tripwire on each group (free, deterministic):")
        for name, result in tripwire_report(all_cases).items():
            print(f"  {name:20} {pct(result['k'], result['n'])}")
        sys.exit(0)

    if found:
        sys.exit("Fix the cases first:\n" + "\n".join(found))
    confirm_paid_run(total, sys.argv)
    run(*cli_path(sys.argv, RESULTS))
