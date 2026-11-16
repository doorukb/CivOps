"""The decision layer: plain code, no model.

`evaluate_incident` walks the stages of the rulebook in a fixed order and
returns the first outcome that applies. The order is the safety argument:

1. tripwire on the raw transcript (nothing the model extracted can clear it)
2. any screening answer that is True
3. any screening answer that is still unknown (unknown is never "no")
4. missing call type or timestamp
5. eligibility and operating hours, where exactly one rule must match

Stages 1-4 always end in human_review; the rulebook loader enforces that.
"""

from datetime import datetime

from app.models import Decision, Destination, Incident
from app.rulebook import (  # noqa: F401 - RulebookError re-exported for callers
    Rulebook,
    RulebookError,
    SafetyOutcome,
    Schedule,
    load_rulebook,
)
from app.services.tripwires import scan_transcript

ENGINE_GUARD_SOURCE = "Rule engine guard: the rulebook must give exactly one answer"


def is_on_duty(schedule: Schedule, local_time: datetime) -> bool:
    """True when `local_time` (already in the schedule's zone) is inside a shift."""
    return (
        local_time.weekday() in schedule.weekdays
        and schedule.start_hour <= local_time.hour < schedule.end_hour
    )


def _safety_decision(
    outcome: SafetyOutcome, rulebook: Rulebook, detail: str = "", **extra
) -> Decision:
    return Decision(
        destination=outcome.destination,
        rule_id=outcome.id,
        reason=f"{outcome.reason}: {detail}" if detail else outcome.reason,
        source=outcome.source,
        rulebook_version=rulebook.version,
        **extra,
    )


def _engine_error(reason: str, rulebook: Rulebook) -> Decision:
    return Decision(
        destination=Destination.HUMAN_REVIEW,
        rule_id="RULEBOOK-ERROR",
        reason=reason,
        source=ENGINE_GUARD_SOURCE,
        rulebook_version=rulebook.version,
    )


def evaluate_incident(
    incident: Incident,
    rulebook: Rulebook | None = None,
    transcript: str | None = None,
) -> Decision:
    if rulebook is None:
        rulebook = load_rulebook()
    screening = rulebook.screening

    # Stage 1: tripwire on the raw transcript
    if transcript is not None:
        tripwire_flags = scan_transcript(transcript)

        if tripwire_flags:
            return _safety_decision(
                screening.tripwire, rulebook, detail=", ".join(tripwire_flags)
            )

    # Stage 2: known safety concerns
    flagged = [
        field for field in screening.safety_fields
        if getattr(incident, field) is True
    ]

    if flagged:
        return _safety_decision(
            screening.escalation, rulebook, detail=", ".join(flagged)
        )

    # Stage 3: incomplete screening
    unknown = [
        field for field in screening.safety_fields
        if getattr(incident, field) is None
    ]

    if unknown:
        return _safety_decision(
            screening.incomplete, rulebook, missing_information=unknown
        )

    # Stage 4: the facts the eligibility rules need
    context = screening.context_incomplete

    if incident.timestamp is None or incident.call_type is None:
        return _safety_decision(
            context,
            rulebook,
            missing_information=[
                field for field in ("call_type", "timestamp")
                if getattr(incident, field) is None
            ],
        )

    timestamp = incident.timestamp

    # A timestamp without a UTC offset cannot be placed in the schedule
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return Decision(
            destination=context.destination,
            rule_id=context.id,
            reason="Timestamp must include timezone information.",
            missing_information=["timestamp_timezone"],
            source=context.source,
            rulebook_version=rulebook.version,
        )

    schedule = rulebook.schedule
    local_time = timestamp.astimezone(schedule.tzinfo)

    facts = {
        "eligible_call_type": incident.call_type in rulebook.eligible_call_types,
        "on_duty": is_on_duty(schedule, local_time),
    }

    # Stage 5: exactly one eligibility rule must match
    matching_rules = [
        rule for rule in rulebook.rules if rule.conditions.matches(facts)
    ]

    if not matching_rules:
        return _engine_error("No matching eligibility rule.", rulebook)

    highest_priority = min(rule.priority for rule in matching_rules)

    top_rules = [
        rule for rule in matching_rules if rule.priority == highest_priority
    ]

    if len(top_rules) != 1:
        return _engine_error("Conflicting eligibility rules.", rulebook)

    rule = top_rules[0]

    # Lowering urgency takes a person: see Decision.provisional.
    unconfirmed = (
        incident.unconfirmed_negatives()
        if rule.destination is not Destination.HUMAN_REVIEW
        else []
    )

    return Decision(
        destination=rule.destination,
        rule_id=rule.id,
        reason=rule.reason,
        eligible=facts["eligible_call_type"],
        on_duty=facts["on_duty"],
        source=rule.source,
        rulebook_version=rulebook.version,
        provisional=bool(unconfirmed),
        needs_confirmation=unconfirmed,
    )
