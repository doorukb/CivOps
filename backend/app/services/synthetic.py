import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Incident, AuditRecord, Destination


CALL_TYPES = [
    "wellbeing_check",
    "disturbance",
    "suspicious",
    "noise_complaint",
    "other",
]


def generate_synthetic_month(
    year: int = 2026,
    month: int = 11,
    count: int = 250,
    seed: int = 42
) -> list[AuditRecord]:
    rng = random.Random(seed)

    start = datetime(year, month, 1, tzinfo=ZoneInfo("America/New_York"))

    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=start.tzinfo)
    else:
        end = datetime(year, month + 1, 1, tzinfo=start.tzinfo)

    total_minutes = int((end - start).total_seconds() / 60)

    records = []

    for index in range(count):
        timestamp = start + timedelta(
            minutes=rng.randrange(total_minutes)
        )

        call_type = rng.choice(CALL_TYPES)

        record = AuditRecord(
            call_id=f"SYN-{index + 1:04d}",
            incident=Incident(
                call_type=call_type,
                weapon_present=False,
                violence=False,
                injury=False,
                immediate_danger=False,
                timestamp=timestamp
            ),
            actual_destination=rng.choice([
                Destination.POLICE,
                Destination.CRESS,
                Destination.HUMAN_REVIEW
            ])
        )

        records.append(record)

    return records