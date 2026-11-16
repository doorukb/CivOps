from fastapi import APIRouter, Query

from app.models import AuditRequest
from app.services.audit import audit_calls, summarize_audit
from app.services.leap_arrivals import ARRIVAL_MODEL
from app.services.synthetic import generate_synthetic_month

router = APIRouter(prefix="/audit", tags=["Monthly Audit"])


@router.post("/run")
def run_audit(request: AuditRequest):
    """Replay your own records (at most 5,000) through the rulebook."""
    results = audit_calls(request.records)

    return {
        "summary": summarize_audit(results),
        "results": results,
    }


@router.get("/demo")
def demo_audit(
    count: int = Query(250, ge=1, le=5_000, description="Synthetic calls to generate"),
    seed: int = Query(42, ge=0, le=2**31 - 1, description="Same seed, same month"),
    year: int = Query(2026, ge=2000, le=2100),
    month: int = Query(11, ge=1, le=12),
):
    """A seeded synthetic month replayed through the rulebook."""
    records = generate_synthetic_month(year=year, month=month, count=count, seed=seed)
    results = audit_calls(records)

    return {
        "dataset": {
            "name": "Synthetic Amherst Dispatch Demo",
            "year": year,
            "month": month,
            "seed": seed,
            "synthetic": True,
            "calibrated_to_leap": ARRIVAL_MODEL.calibrated_to_leap,
            "arrival_pattern": (
                f"{ARRIVAL_MODEL.timing_note} Call mix, the line each call "
                "came in on, safety answers and ‘actual’ outcomes are invented."
            ),
            "count": len(records),
        },
        "summary": summarize_audit(results),
        "results": results,
    }
