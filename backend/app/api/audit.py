from fastapi import APIRouter

from app.models import AuditRequest
from app.services.audit import audit_calls, summarize_audit
from app.services.synthetic import generate_synthetic_month

router = APIRouter(prefix="/audit", tags=["Monthly Audit"])


@router.post("/run")
def run_audit(request: AuditRequest):
    results = audit_calls(request.records)
    summary = summarize_audit(results)

    return {
        "summary": summary,
        "results": results
    }

@router.get("/demo")
def demo_audit():
    records = generate_synthetic_month(
        year=2026,
        month=11,
        count=250,
        seed=42
    )

    results = audit_calls(records)
    summary = summarize_audit(results)

    return {
        "dataset": {
            "name": "Synthetic Amherst Dispatch Demo",
            "year": 2026,
            "month": 11,
            "synthetic": True,
            "calibrated_to_leap": False,
            "arrival_pattern": (
                "Call timing is fitted to the coverage totals the brief "
                "calculated from LEAP's 2019 hour-of-day and day-of-week "
                "tables, not to LEAP's raw call records. Call mix, safety "
                "answers and ‘actual’ outcomes are invented."
            ),
            "count": len(records)
        },
        "summary": summary,
        "results": results
    }