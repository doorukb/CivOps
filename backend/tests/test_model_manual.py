# from app.models import Incident

# incident = Incident(
#     weapon_present=False
# )

# print(incident)

# from app.models import Incident, CallType

# incident = Incident(
#     call_type=CallType.WELLBEING_CHECK,
#     weapon_present=False,
#     injury=False,
#     timestamp="2026-11-16T14:30:00-05:00",
#     source_line="non_emergency",
#     evidence={
#         "weapon_present": "I haven't seen any weapons."
#     }
# )

# print(incident.model_dump(mode="json"))

# from app.models import Decision, Destination

# decision = Decision(
#     destination=Destination.HUMAN_REVIEW,
#     rule_id="SCREEN-001",
#     reason="Weapon status is unknown.",
#     missing_information=["weapon_present"]
# )

# print(decision.model_dump(mode="json"))

from app.models import Incident
from app.services.rule_engine import load_rules, matches_rule

rules = load_rules()

incident = Incident(
    call_type="wellbeing_check",
    weapon_present=False
)

print(matches_rule(incident, rules[0]))