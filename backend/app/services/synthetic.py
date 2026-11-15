import random

from app.models import AuditRecord, Destination, Incident
from app.services.arrival_patterns import random_timestamp

CALL_TYPES = [
    "wellbeing_check",
    "disturbance",
    "suspicious",
    "noise_complaint",
    "other",
]

# ---------------------------------------------------------------------------
# ASSUMPTIONS about what dispatch "actually" did. These are deliberately
# independent of rules/dispatch.yaml so the audit can disagree with dispatch.
# None of these rates is measured; they are demo inputs.
# ---------------------------------------------------------------------------

# When CRESS really works (Monday=0 .. Friday=4, 08:00 up to 16:00 local).
ACTUAL_CRESS_WEEKDAYS = (0, 1, 2, 3, 4)
ACTUAL_CRESS_START_HOUR = 8
ACTUAL_CRESS_END_HOUR = 16

# Call types dispatch considers referable to CRESS (noise complaints excluded).
ACTUAL_REFERRABLE_TYPES = ("wellbeing_check", "disturbance", "suspicious")

# Share of referrable calls, arriving while CRESS works and with no true
# safety flag, that dispatch actually refers.
ACTUAL_REFERRAL_RATE = 0.25

# Share of other calls arriving while CRESS works that dispatch sends to
# CRESS anyway (any type, any safety answer): a misroute.
ACTUAL_MISROUTE_RATE = 0.03

# Share of calls with exactly one true / exactly one unknown safety answer.
# The two are mutually exclusive; every other call has all four answers False.
TRUE_SAFETY_RATE = 0.08
UNKNOWN_SAFETY_RATE = 0.05

SAFETY_FIELDS = ("weapon_present", "violence", "injury", "immediate_danger")


def cress_on_duty(timestamp) -> bool:
    return (
        timestamp.weekday() in ACTUAL_CRESS_WEEKDAYS
        and ACTUAL_CRESS_START_HOUR <= timestamp.hour < ACTUAL_CRESS_END_HOUR
    )


def generate_synthetic_month(
    year: int = 2026,
    month: int = 11,
    count: int = 250,
    seed: int = 42
) -> list[AuditRecord]:
    rng = random.Random(seed)
    records = []

    for index in range(count):
        timestamp = random_timestamp(rng, year, month)
        call_type = rng.choice(CALL_TYPES)

        # Draw everything for a call up front so the sequence per call
        # does not depend on which branch it takes.
        safety_draw = rng.random()
        flagged_field = rng.choice(SAFETY_FIELDS)
        referral_draw = rng.random()
        misroute_draw = rng.random()

        safety = {field: False for field in SAFETY_FIELDS}
        has_true_flag = safety_draw < TRUE_SAFETY_RATE

        if has_true_flag:
            safety[flagged_field] = True
        elif safety_draw < TRUE_SAFETY_RATE + UNKNOWN_SAFETY_RATE:
            safety[flagged_field] = None

        if safety["injury"] is True:
            destination = Destination.FIRE_EMS
        else:
            destination = Destination.POLICE

        if cress_on_duty(timestamp):
            referred = (
                call_type in ACTUAL_REFERRABLE_TYPES
                and not has_true_flag
                and referral_draw < ACTUAL_REFERRAL_RATE
            )

            if referred or misroute_draw < ACTUAL_MISROUTE_RATE:
                destination = Destination.CRESS

        records.append(AuditRecord(
            call_id=f"SYN-{index + 1:04d}",
            incident=Incident(
                call_type=call_type,
                timestamp=timestamp,
                **safety
            ),
            actual_destination=destination
        ))

    return records
