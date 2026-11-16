import calendar
import random
from datetime import datetime

from app.models import SAFETY_FIELDS, AuditRecord, Destination, Incident
from app.services.leap_arrivals import (
    CALL_TYPE_WEIGHTS,
    DAY_WEIGHTS,
    HOUR_WEIGHTS,
    NON_EMERGENCY_LINE_SHARE,
    TIMEZONE,
)

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


def random_timestamp(rng: random.Random, year: int, month: int) -> datetime:
    """Draw a local timestamp in the month from the shared hour/day weights."""
    days = range(1, calendar.monthrange(year, month)[1] + 1)
    day = rng.choices(
        days,
        [DAY_WEIGHTS[datetime(year, month, d).weekday()] for d in days],
    )[0]
    hour = rng.choices(range(24), HOUR_WEIGHTS)[0]

    return datetime(
        year, month, day, hour, rng.randrange(60), tzinfo=TIMEZONE
    )


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
    call_types, type_weights = zip(*CALL_TYPE_WEIGHTS, strict=True)
    records = []

    for index in range(count):
        timestamp = random_timestamp(rng, year, month)
        # Same call mix as the What-If simulator (one shared arrival model).
        call_type = rng.choices(call_types, type_weights)[0]

        # Draw everything for a call up front so the sequence per call
        # does not depend on which branch it takes.
        safety_draw = rng.random()
        flagged_field = rng.choice(SAFETY_FIELDS)
        referral_draw = rng.random()
        misroute_draw = rng.random()
        line = "non_emergency" if rng.random() < NON_EMERGENCY_LINE_SHARE else "911"

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
                source_line=line,
                **safety
            ),
            actual_destination=destination
        ))

    return records
