"""Monthly replay audit: run recorded calls through the rulebook and sort them
into the four review groups the town described."""

from collections import Counter
from datetime import datetime

from app.models import AuditRecord
from app.rulebook import Rulebook, Schedule, load_rulebook
from app.services.rule_engine import evaluate_incident

# The "eligible but after hours" group looks at the hours right after CRESS's
# shift ends: the calls an extension of the shift would pick up first.
REVIEW_WINDOW_HOURS = 4


def review_window(schedule: Schedule) -> dict:
    """The after-hours review window, derived from the rulebook's schedule so it
    follows the shift end if the rulebook changes (16 -> "4 PM to 8 PM")."""
    start = schedule.end_hour
    end = start + REVIEW_WINDOW_HOURS

    def clock(hour: int) -> str:
        hour %= 24
        return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"

    return {
        "start_hour": start,
        "end_hour": end,
        "label": f"{clock(start)} to {clock(end)}",
        # Any day of the week counts, weekends included: on days without a
        # shift the same clock hours are still the first ones an extension
        # would cover.
        "days": "every day",
    }


def in_review_window(schedule: Schedule, local_time: datetime) -> bool:
    start = schedule.end_hour % 24
    return (local_time.hour - start) % 24 < REVIEW_WINDOW_HOURS


def audit_calls(
    records: list[AuditRecord], rulebook: Rulebook | None = None
) -> list[dict]:
    """Replay each record through the rulebook, loaded once for the whole run."""
    if rulebook is None:
        rulebook = load_rulebook()

    results = []

    for record in records:
        decision = evaluate_incident(
            record.incident, rulebook, transcript=record.transcript
        )
        timestamp = record.incident.timestamp

        results.append(classify_audit_result({
            "call_id": record.call_id,
            "call_type": (
                record.incident.call_type.value if record.incident.call_type else None
            ),
            "source_line": record.incident.source_line,
            "actual_destination": record.actual_destination.value,
            "recommended_destination": decision.destination.value,
            "rule_id": decision.rule_id,
            "reason": decision.reason,
            "source": decision.source,
            "eligible": decision.eligible,
            "on_duty": decision.on_duty,
            "timestamp": timestamp.isoformat() if timestamp else None,
        }, rulebook.schedule))

    return results


def classify_audit_result(result: dict, schedule: Schedule | None = None) -> dict:
    if schedule is None:
        schedule = load_rulebook().schedule

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

    # Eligible, off duty, in the hours right after the shift
    local_hour = None
    in_window = False

    if result["timestamp"] is not None:
        timestamp = datetime.fromisoformat(result["timestamp"])
        if timestamp.tzinfo is not None:
            local_time = timestamp.astimezone(schedule.tzinfo)
            local_hour = local_time.hour
            in_window = in_review_window(schedule, local_time)

    result["local_hour"] = local_hour
    result["eligible_after_hours"] = (
        result["eligible"] is True
        and result["on_duty"] is False
        and in_window
    )

    return result


GROUPS = (
    "sent_to_cress_appropriately",
    "could_have_gone_to_cress",
    "should_not_have_gone_to_cress",
    "eligible_after_hours",
)


def summarize_audit(results: list[dict], rulebook: Rulebook | None = None) -> dict:
    if rulebook is None:
        rulebook = load_rulebook()

    could_have = [r for r in results if r["could_have_gone_to_cress"]]

    return {
        "total_calls": len(results),
        **{group: sum(r[group] for r in results) for group in GROUPS},
        "review_window": review_window(rulebook.schedule),
        "rulebook_version": rulebook.version,
        # Display-only breakdown: no rule reads the line a call came in on.
        "could_have_gone_by_line": dict(
            Counter(r.get("source_line") or "unknown" for r in could_have)
        ),
        "by_rule": dict(Counter(r["rule_id"] for r in results)),
    }
