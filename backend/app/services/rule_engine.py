from pathlib import Path
import yaml
from app.models import Incident, Decision, Destination

RULEBOOK_PATH = (
    Path(__file__).resolve().parents[2] / "rules" / "dispatch.yaml"
)

def load_rules():
    with open(RULEBOOK_PATH, "r", encoding="utf-8") as file:
        rulebook = yaml.safe_load(file)

    return rulebook["rules"]

def matches_rule(incident, rule):
    for field, expected_value in rule["conditions"].items():
        actual_value = getattr(incident, field)

        if actual_value != expected_value:
            return False

    return True


def evaluate_incident(incident: Incident) -> Decision:
    rules = load_rules()

    matching_rules = [
        rule for rule in rules
        if matches_rule(incident, rule)
    ]

    if len(matching_rules) != 1:
        return Decision(
            destination=Destination.HUMAN_REVIEW,
            rule_id="RULEBOOK-ERROR",
            reason=f"Expected 1 matching rule, found {len(matching_rules)}"
        )

    rule = matching_rules[0]

    return Decision(
        destination=Destination(rule["destination"]),
        rule_id=rule["id"],
        reason=rule["reason"]
    )