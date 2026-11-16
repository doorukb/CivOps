"""Free checks on the v2 evaluation sets and their scoring. Never calls the API."""

import json

import pytest

from app.services.extractor import ExtractedIncident, verify
from eval import bias_pairs_v2, escalation_v2, extraction_accuracy
from eval.common import confirm_paid_run, provenance, rate, write_results
from eval.missed_escalations import CASES as V1_CASES

SAFETY = ("weapon_present", "violence", "injury", "immediate_danger")


# --- the pre-registered case files are well formed ---------------------------

def test_escalation_v2_cases_are_valid():
    assert escalation_v2.check_cases() == []


def test_bias_pairs_v2_are_valid():
    assert bias_pairs_v2.check_pairs() == []


def test_extraction_gold_set_is_valid():
    assert extraction_accuracy.check_cases() == []


def test_escalation_v2_reuses_the_v1_emergencies_unchanged():
    cases = escalation_v2.load_cases()["emergencies"]
    reused = {c["id"]: c["text"] for c in cases if c["id"].startswith("v1_")}

    assert reused == {f"v1_{case_id}": text for case_id, text in V1_CASES}
    assert sum(c["form"] == "dialogue" for c in cases) == 13


def test_tripwire_report_is_free_and_matches_the_design():
    report = escalation_v2.tripwire_report(escalation_v2.load_cases())

    assert report["emergencies"]["k"] == 0          # the premise of the eval
    assert report["hard_negatives"]["share"] == 1   # flagged by design
    assert report["controls"]["n"] == 18


# --- escalation scoring ------------------------------------------------------

def esc_row(group, bucket, form="dialogue", expect=None, rule_id=None, provisional=False, tripwire=False):
    rule = rule_id or {
        "safety_escalation": "SAFETY-ESCALATION", "incomplete_screening": "SCREEN-INCOMPLETE",
        "to_cress": "CRESS-001", "other_review": "REVIEW-001",
    }[bucket]
    return {
        "id": f"{group}-{bucket}", "group": group, "form": form, "expect": expect,
        "bucket": bucket, "rule_id": rule, "provisional": provisional, "tripwire": tripwire,
    }


def test_escalation_summary_reports_both_rates_and_separates_weak_catches():
    rows = (
        [esc_row("emergencies", "safety_escalation")] * 6
        + [esc_row("emergencies", "incomplete_screening", form="paragraph")] * 3
        + [esc_row("emergencies", "to_cress", provisional=True)]
        + [esc_row("controls", "to_cress", expect="CRESS-001")] * 7
        + [esc_row("controls", "safety_escalation", expect="CRESS-001")] * 2
        + [esc_row("controls", "incomplete_screening", expect="CRESS-001")]
        + [esc_row("paragraph_controls", "incomplete_screening", form="paragraph")] * 4
        + [esc_row("hard_negatives", "incomplete_screening", form="paragraph", tripwire=True)] * 2
        + [{"id": "broken", "group": "controls", "error": "APIConnectionError"}]
    )

    summary = escalation_v2.summarize(rows)

    emergencies, controls = summary["emergencies"], summary["controls"]
    assert emergencies["recognised"]["k"] == 6 and emergencies["recognised"]["n"] == 10
    assert emergencies["incomplete_only"]["k"] == 3   # not counted as recognised
    assert emergencies["missed"]["k"] == 1
    assert emergencies["missed_but_provisional"] == 1
    assert emergencies["screened_dialogues"]["missed"] == rate(1, 7)
    assert controls["false_escalation"] == rate(2, 10)
    assert controls["left_incomplete"]["k"] == 1
    assert controls["reached_expected_rule"]["k"] == 7
    assert summary["paragraph_controls"]["incomplete_as_expected"]["share"] == 1
    assert summary["hard_negatives"]["tripwire_flagged"]["k"] == 2
    assert summary["errors"] == 1


def test_a_system_that_escalates_everything_no_longer_looks_perfect():
    """The flaw in v1: with no controls, 'escalate everything' scored 100%."""
    cases = escalation_v2.load_cases()
    rows = [
        esc_row(c["group"], "safety_escalation", form=c["form"], expect=c["expect"])
        for group in escalation_v2.GROUPS for c in cases[group]
    ]

    summary = escalation_v2.summarize(rows)

    assert summary["emergencies"]["recognised"]["share"] == 1
    assert summary["controls"]["false_escalation"]["share"] == 1  # and now it shows


# --- bias-pair analysis ------------------------------------------------------

def outcome(rule_id, destination="human_review", **fields):
    base = {"call_type": "suspicious", **dict.fromkeys(SAFETY, False), "caller_requests_cress": None}
    return bias_pairs_v2.Outcome(
        fields={**base, **fields}, rule_id=rule_id, destination=destination, provisional=False
    )


CRESS = outcome("CRESS-001", "cress")
INCOMPLETE = outcome("SCREEN-INCOMPLETE", weapon_present=None)
ESCALATED = outcome("SAFETY-ESCALATION", weapon_present=True)


def bias_row(pair, a, b, dimension="race", template="object"):
    return {"pair": pair, "dimension": dimension, "template": template, "results": {"A": a, "B": b}}


def test_bias_analysis_compares_versions_against_the_noise_floor():
    rows = [
        bias_row(0, [CRESS, CRESS, CRESS], [CRESS, CRESS, CRESS], template="clear"),
        bias_row(1, [INCOMPLETE, INCOMPLETE, INCOMPLETE], [ESCALATED, INCOMPLETE, INCOMPLETE]),
    ]

    summary = bias_pairs_v2.analyse(rows, runs=3)

    assert summary["between_versions"]["decision_differs"] == rate(1, 6)
    # Same text, different runs: B of pair 1 disagrees with itself in 2 of 3 combinations.
    assert summary["noise_floor_same_text"]["decision_differs"] == rate(2, 12)
    assert summary["routing_informative"] is True
    assert summary["decision_distribution"] == {
        "cress/CRESS-001": 6, "human_review/SCREEN-INCOMPLETE": 5,
        "human_review/SAFETY-ESCALATION": 1,
    }
    assert summary["pairs_where_decision_differed"] == [{
        "pair": 1, "dimension": "race", "template": "object", "run": 0,
        "A": "human_review/SCREEN-INCOMPLETE", "B": "human_review/SAFETY-ESCALATION",
    }]
    assert summary["by_template"]["clear"]["decision_differs"]["k"] == 0


def test_bias_analysis_flags_a_degenerate_run_instead_of_reporting_agreement():
    """v1's failure mode: every run at SCREEN-INCOMPLETE. 100% 'agreement'
    there means nothing, and the analysis must say so."""
    rows = [bias_row(i, [INCOMPLETE] * 3, [INCOMPLETE] * 3) for i in range(4)]

    summary = bias_pairs_v2.analyse(rows, runs=3)

    assert summary["between_versions"]["decision_differs"]["k"] == 0
    assert summary["routing_informative"] is False


def test_bias_analysis_skips_failed_calls():
    summary = bias_pairs_v2.analyse([bias_row(0, [CRESS, None, CRESS], [CRESS, CRESS, CRESS])], runs=3)

    assert summary["between_versions"]["decision_differs"]["n"] == 2
    assert summary["errors"] == 1


def test_bias_templates_differ_only_in_the_changed_detail():
    data = bias_pairs_v2.load_pairs()

    for pair in data["pairs"]:
        texts = bias_pairs_v2.versions(data, pair)
        assert texts["A"].replace(pair["a"], "X") == texts["B"].replace(pair["b"], "X")


# --- extraction-accuracy scoring ---------------------------------------------

def acc_row(case_id, gold, predicted, category="plain"):
    full = {"call_type": "wellbeing_check", **dict.fromkeys(SAFETY, False), "caller_requests_cress": None}
    return {
        "id": case_id, "category": category,
        "gold": {**full, **gold}, "predicted": {**full, **predicted}, "downgraded": [],
    }


def test_accuracy_separates_the_errors_by_what_they_cost():
    rows = [
        acc_row("all_right", {}, {}),
        acc_row("missed", {"weapon_present": True}, {"weapon_present": False}, "positive"),
        acc_row("missed_as_unknown", {"injury": True}, {"injury": None}, "positive"),
        acc_row("unknown_as_no", {"violence": None}, {"violence": False}, "hedge"),
        acc_row("cautious", {"injury": False}, {"injury": None}),
        acc_row("cautious_yes", {"injury": None}, {"injury": True}, "partial"),
        acc_row("wrong_type", {"call_type": "disturbance"}, {"call_type": "noise_complaint"}),
    ]

    summary = extraction_accuracy.score(rows)
    answers = summary["screening_answers"]

    assert answers["missed_concern"] == rate(2, 2)            # of the 2 gold-true answers
    assert answers["unknown_treated_as_no"] == rate(1, 2)     # of the 2 gold-unknown answers
    assert answers["over_caution"]["k"] == 2
    assert summary["error_examples"]["unknown_treated_as_no"] == ["unknown_as_no.violence"]
    assert summary["per_field_accuracy"]["call_type"]["k"] == 6
    assert summary["per_field_accuracy"]["weapon_present"]["k"] == 6
    assert summary["all_six_fields_correct"]["k"] == 1
    assert summary["confusion"]["violence"]["None->False"] == 1


def test_accuracy_accepts_any_listed_call_type():
    rows = [
        acc_row("either", {"call_type": ["wellbeing_check", "other"]}, {"call_type": "other"}),
        acc_row("neither", {"call_type": ["wellbeing_check", "other"]}, {"call_type": "disturbance"}),
        acc_row("null_ok", {"call_type": [None, "other"]}, {"call_type": None}),
    ]

    assert extraction_accuracy.score(rows)["per_field_accuracy"]["call_type"]["k"] == 2


def test_hedge_check_rescues_every_negation_trap_in_the_gold_set():
    """Deterministic, free, and independent of any model: if an overconfident
    model answered 'no' on every hedged denial in the gold set, quoting the
    caller's reply, the hedge check would reset each one to unknown."""
    cases = [c for c in extraction_accuracy.load_cases()["cases"] if c["category"] == "hedge"]
    questions = {
        "weapon_present": "weapons", "violence": "violent",
        "injury": "injured", "immediate_danger": "immediate danger",
    }
    assert len(cases) == 8

    for case in cases:
        findings = {}
        for field, topic in questions.items():
            asked = next(i for i, (_, text) in enumerate(case["lines"]) if topic in text.lower())
            reply = case["lines"][asked + 1][1]
            findings[field] = {"value": False, "evidence": reply.rstrip(".")}

        overconfident = ExtractedIncident(
            call_type=case["gold"]["call_type"], caller_requests_cress=None, **findings
        )
        result = verify(overconfident, case["text"])

        for field in questions:
            assert getattr(result, field) == case["gold"][field], (case["id"], field)


# --- provenance and spend guards ---------------------------------------------

def test_every_results_file_records_who_produced_it(monkeypatch):
    monkeypatch.setenv("DESPATCH_EXTRACTION_MODEL", "claude-haiku-5-5")

    meta = provenance("escalation_v2", 70)

    assert meta["model"] == "claude-haiku-5-5"
    assert len(meta["extractor_prompt_sha256"]) == 64
    assert meta["n"] == 70 and meta["synthetic"] is True
    assert meta["rulebook_version"] and meta["run_date"]
    assert "not settable" in meta["temperature"]


def test_results_are_never_overwritten_by_accident(tmp_path):
    path = tmp_path / "v2" / "result.json"
    write_results(path, {"a": 1})

    with pytest.raises(SystemExit, match="already exists"):
        write_results(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}

    write_results(path, {"a": 3}, overwrite=True)
    assert json.loads(path.read_text()) == {"a": 3}


def test_a_paid_run_needs_an_explicit_yes():
    with pytest.raises(SystemExit, match="96 paid"):
        confirm_paid_run(96, ["eval.bias_pairs_v2"])

    confirm_paid_run(96, ["eval.bias_pairs_v2", "--yes"])  # does not exit


def test_no_v2_results_exist_until_someone_runs_the_paid_step():
    """Documents the current state: v2 is pre-registered, not run. When the
    runs are done and the results are committed, delete this test and put the
    numbers (with their meta block) in docs/EVALUATION.md."""
    from eval.common import RESULTS_DIR

    assert not (RESULTS_DIR / "v2").exists()
    assert sorted(p.name for p in (RESULTS_DIR / "v1").glob("*.json")) == [
        "bias_pairs.json", "missed_escalations.json",
    ]
