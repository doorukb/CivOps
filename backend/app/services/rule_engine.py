from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from app.services.tripwires import scan_transcript

import yaml

from app.models import Incident, Decision, Destination


RULEBOOK_PATH = (
    Path(__file__).resolve().parents[2] / "rules" / "dispatch.yaml"
)


def load_rulebook():
    with open(RULEBOOK_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def matches_rule(facts, rule):
    return all(
        facts.get(field) == expected
        for field, expected in rule["conditions"].items()
    )


def evaluate_incident(
    incident: Incident,
    rulebook: dict | None = None,
    transcript: str | None = None
) -> Decision:
    if rulebook is None:
        rulebook = load_rulebook()
    screening = rulebook["screening"]

    if transcript is not None:
        tripwire_flags = scan_transcript(transcript)

        if tripwire_flags:
            categories = ", ".join(tripwire_flags.keys())

            return Decision(
                destination=Destination.HUMAN_REVIEW,
                rule_id="TRANSCRIPT-TRIPWIRE",
                reason=f"Transcript contains potential safety signals: {categories}",
                source="Illustrative transcript safety screening"
            )

    # Stage 1: Known safety concerns
    flagged = [
        field for field in screening["safety_fields"]
        if getattr(incident, field) is True
    ]

    if flagged:
        config = screening["escalation"]

        return Decision(
            destination=Destination(config["destination"]),
            rule_id=config["id"],
            reason=f'{config["reason"]}: {", ".join(flagged)}'
        )

    # Stage 2: Incomplete screening
    unknown = [
        field for field in screening["safety_fields"]
        if getattr(incident, field) is None
    ]

    if unknown:
        config = screening["incomplete"]

        return Decision(
            destination=Destination(config["destination"]),
            rule_id=config["id"],
            reason=config["reason"],
            missing_information=unknown
        )

    # Stage 3: Check call eligibility and operating hours
    schedule = rulebook["schedule"]

    if incident.timestamp is None or incident.call_type is None:
        return Decision(
            destination=Destination.HUMAN_REVIEW,
            rule_id="CONTEXT-INCOMPLETE",
            reason="Call type or timestamp is missing.",
            missing_information=[
                field for field in ("call_type", "timestamp")
                if getattr(incident, field) is None
            ]
        )

    timestamp = incident.timestamp

    # Reject timestamps without timezone information
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return Decision(
            destination=Destination.HUMAN_REVIEW,
            rule_id="CONTEXT-INCOMPLETE",
            reason="Timestamp must include timezone information.",
            missing_information=["timestamp_timezone"]
        )

    local_time = timestamp.astimezone(
        ZoneInfo(schedule["timezone"])
    )

    on_duty = (
        local_time.weekday() in schedule["weekdays"]
        and schedule["start_hour"] <= local_time.hour < schedule["end_hour"]
    )

    facts = {
        "eligible_call_type": (
            incident.call_type.value in rulebook["eligible_call_types"]
        ),
        "on_duty": on_duty
    }

    # Stage 4: Find exactly one matching eligibility rule
    matching_rules = [
        rule for rule in rulebook["rules"]
        if matches_rule(facts, rule)
    ]

    if not matching_rules:
        return Decision(
            destination=Destination.HUMAN_REVIEW,
            rule_id="RULEBOOK-ERROR",
            reason="No matching eligibility rule."
        )

    highest_priority = min(
        rule["priority"] for rule in matching_rules
    )

    top_rules = [
        rule for rule in matching_rules
        if rule["priority"] == highest_priority
    ]

    if len(top_rules) != 1:
        return Decision(
            destination=Destination.HUMAN_REVIEW,
            rule_id="RULEBOOK-ERROR",
            reason="Conflicting eligibility rules."
        )

    rule = top_rules[0]

    return Decision(
        destination=Destination(rule["destination"]),
        rule_id=rule["id"],
        reason=rule["reason"],
        eligible=facts["eligible_call_type"],
        on_duty=facts["on_duty"],
        source=rule.get("source")
    )