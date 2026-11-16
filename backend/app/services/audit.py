from zoneinfo import ZoneInfo

from app.models import AuditRecord
from app.services.rule_engine import evaluate_incident


def audit_calls(records: list[AuditRecord]) -> list[dict]:
    results = []

    for record in records:
        decision = evaluate_incident(
            record.incident, transcript=record.transcript
        )

        results.append(classify_audit_result({
            "call_id": record.call_id,
            "actual_destination": record.actual_destination.value,
            "recommended_destination": decision.destination.value,
            "rule_id": decision.rule_id,
            "reason": decision.reason,
            "eligible": decision.eligible,
            "on_duty": decision.on_duty,
            "timestamp": (record.incident.timestamp.isoformat()
                if record.incident.timestamp else None)
        }))

    return results

def classify_audit_result(result: dict) -> dict:
    actual = result["actual_destination"]
    recommended = result["recommended_destination"]

    # Appropriate CRESS referral
    result["sent_to_cress_appropriately"] = (
        actual == "cress"
        and recommended == "cress"
    )

    # Potential missed CRESS referral
    result["could_have_gone_to_cress"] = (
        actual != "cress"
        and recommended == "cress"
    )

    # Potential inappropriate CRESS referral
    result["should_not_have_gone_to_cress"] = (
        actual == "cress"
        and recommended != "cress"
    )

    # After-hours eligibility
    timestamp_str = result["timestamp"]

    in_evening_window = False

    if timestamp_str is not None:
        from datetime import datetime

        local_time = datetime.fromisoformat(
            timestamp_str
        ).astimezone(ZoneInfo("America/New_York"))

        in_evening_window = (
            16 <= local_time.hour < 20
        )

    result["eligible_after_hours"] = (
        result["eligible"] is True
        and result["on_duty"] is False
        and in_evening_window
    )

    return result

def summarize_audit(results: list[dict]) -> dict:
    return {
        "total_calls": len(results),
        "sent_to_cress_appropriately": sum(
            r["sent_to_cress_appropriately"] for r in results
        ),
        "could_have_gone_to_cress": sum(
            r["could_have_gone_to_cress"] for r in results
        ),
        "should_not_have_gone_to_cress": sum(
            r["should_not_have_gone_to_cress"] for r in results
        ),
        "eligible_after_hours": sum(
            r["eligible_after_hours"] for r in results
        ),
    }