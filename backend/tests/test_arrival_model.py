"""The arrival model is data with sources and an honest provenance flag (G-01, R-04)."""

from collections import Counter
from copy import deepcopy

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import CallType
from app.services.leap_arrivals import (
    ARRIVAL_MODEL,
    ARRIVAL_MODEL_PATH,
    CALL_TYPE_WEIGHTS,
    NON_EMERGENCY_LINE_SHARE,
    ArrivalModel,
)
from app.services.synthetic import generate_synthetic_month

client = TestClient(app)
RAW = yaml.safe_load(ARRIVAL_MODEL_PATH.read_text(encoding="utf-8"))


def test_shipped_model_is_labelled_fitted_and_every_number_has_a_source():
    assert ARRIVAL_MODEL.provenance == "fitted"
    assert ARRIVAL_MODEL.calibrated_to_leap is False
    for name in ("hour_weights", "day_weights", "call_type_weights",
                 "calls_per_week", "non_emergency_line_share"):
        assert getattr(ARRIVAL_MODEL, name).source.strip(), name
    assert "not copied from" in ARRIVAL_MODEL.timing_note


def test_the_api_cannot_claim_calibration_the_data_does_not_have():
    assert client.get("/audit/demo").json()["dataset"]["calibrated_to_leap"] is False
    assert client.get("/simulation/baseline").json()["calibrated_to_leap"] is False
    compared = client.post("/simulation/compare", json={"scenario": {}, "replications": 2}).json()
    assert compared["calibrated_to_leap"] is False
    assert "fitted" in compared["assumptions"][0]


def test_swapping_in_real_tables_is_a_data_only_change():
    """With provenance: leap_tables the same code reports calibrated timing."""
    data = deepcopy(RAW)
    data["provenance"] = "leap_tables"
    data["hour_weights"]["source"] = "LEAP report, p. N (hour-of-day table)"

    model = ArrivalModel.model_validate(data)

    assert model.calibrated_to_leap is True
    assert "published in LEAP's analysis" in model.timing_note


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda d: d["hour_weights"]["values"].append(0.0), "24 values"),
        (lambda d: d["day_weights"]["values"].append(0.0), "7 values"),
        (lambda d: d["hour_weights"]["values"].__setitem__(0, 0.5), "sum to 1"),
        (lambda d: d["day_weights"]["values"].__setitem__(0, -0.132), "negative"),
        (lambda d: d["call_type_weights"]["values"].pop("other"), "every call type"),
        (lambda d: d["hour_weights"].pop("source"), "source"),
        (lambda d: d.update(provenance="measured"), "provenance"),
        (lambda d: d["non_emergency_line_share"].update(value=1.4), "between 0 and 1"),
    ],
)
def test_a_broken_arrival_file_fails_at_load(mutate, problem):
    data = deepcopy(RAW)
    mutate(data)

    with pytest.raises(ValidationError, match=problem):
        ArrivalModel.model_validate(data)


def test_audit_month_uses_the_same_call_mix_as_the_simulator():
    """It used to draw call types uniformly (20% each) while the simulator
    used the weighted mix."""
    records = generate_synthetic_month(count=6_000, seed=3)
    shares = Counter(r.incident.call_type for r in records)

    for call_type, weight in CALL_TYPE_WEIGHTS:
        assert shares[call_type] / len(records) == pytest.approx(weight, abs=0.02)
    assert set(shares) == set(CallType)


def test_audit_records_carry_the_line_the_call_came_in_on():
    records = generate_synthetic_month(count=6_000, seed=3)
    lines = Counter(r.incident.source_line for r in records)

    assert set(lines) == {"911", "non_emergency"}
    assert lines["non_emergency"] / len(records) == pytest.approx(
        NON_EMERGENCY_LINE_SHARE, abs=0.02
    )


def test_baseline_endpoint_reads_the_schedule_from_the_rulebook():
    body = client.get("/simulation/baseline").json()

    assert body["baseline"] == {
        "start_hour": 8, "end_hour": 16, "teams": 3, "average_duration_minutes": 60,
        "include_weekends": False, "include_noise_complaints": False,
    }
    presets = {p["id"]: p for p in body["presets"]}
    assert presets["leap_recommended"]["config"]["end_hour"] == 26
    assert presets["leap_recommended"]["schedule_coverage"] == pytest.approx(0.87, abs=0.01)
    assert presets["extend_to_8pm"]["schedule_coverage"] == pytest.approx(0.36, abs=0.01)
