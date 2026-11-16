"""Shared source of call-arrival timing for the audit generator and the simulator.

The numbers live in app/data/arrival_model.yaml, with a `source` beside each
set and a `provenance` flag that says whether they are fitted or copied from
LEAP's tables. Read the honesty note at the top of that file before quoting
anything derived from these weights.
"""

import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CallType, Incident

ARRIVAL_MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "arrival_model.yaml"


class _Sourced(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)


class _Shares(_Sourced):
    values: tuple[float, ...]

    @model_validator(mode="after")
    def shares_sum_to_one(self):
        if any(value < 0 for value in self.values):
            raise ValueError("weights cannot be negative")
        if abs(sum(self.values) - 1) > 1e-6:
            raise ValueError(f"weights must sum to 1, got {sum(self.values):.6f}")
        return self


class _CallTypeShares(_Sourced):
    values: dict[CallType, float]

    @model_validator(mode="after")
    def shares_sum_to_one(self):
        if set(self.values) != set(CallType):
            raise ValueError("call_type_weights must list every call type exactly once")
        if abs(sum(self.values.values()) - 1) > 1e-6:
            raise ValueError("call_type_weights must sum to 1")
        return self


class _Number(_Sourced):
    value: float = Field(gt=0)


class ArrivalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["fitted", "leap_tables"]
    hour_weights: _Shares
    day_weights: _Shares
    call_type_weights: _CallTypeShares
    calls_per_week: _Number
    non_emergency_line_share: _Number

    @model_validator(mode="after")
    def shapes(self):
        if len(self.hour_weights.values) != 24:
            raise ValueError("hour_weights needs 24 values (hours 0 to 23)")
        if len(self.day_weights.values) != 7:
            raise ValueError("day_weights needs 7 values (Monday to Sunday)")
        if self.non_emergency_line_share.value > 1:
            raise ValueError("non_emergency_line_share is a share between 0 and 1")
        return self

    @property
    def calibrated_to_leap(self) -> bool:
        return self.provenance == "leap_tables"

    @property
    def timing_note(self) -> str:
        if self.calibrated_to_leap:
            return (
                "Call timing follows the hour-of-day and day-of-week shares "
                "published in LEAP's analysis of 2019 calls, assuming hour and "
                "day are independent."
            )
        return (
            "Call timing is fitted to the coverage totals calculated from "
            "LEAP's 2019 hour-of-day and day-of-week figures, not copied from "
            "LEAP's tables or raw call records."
        )


def load_arrival_model(path: Path = ARRIVAL_MODEL_PATH) -> ArrivalModel:
    return ArrivalModel.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


ARRIVAL_MODEL = load_arrival_model()

# Share of calls arriving in each clock hour (0-23). Sums to 1.
HOUR_WEIGHTS = ARRIVAL_MODEL.hour_weights.values

# Share of calls per weekday, Monday=0 ... Sunday=6. Sums to 1.
DAY_WEIGHTS = ARRIVAL_MODEL.day_weights.values

# (call type, share) in enum order.
CALL_TYPE_WEIGHTS = tuple(
    (call_type, ARRIVAL_MODEL.call_type_weights.values[call_type]) for call_type in CallType
)

CALLS_PER_WEEK = ARRIVAL_MODEL.calls_per_week.value
NON_EMERGENCY_LINE_SHARE = ARRIVAL_MODEL.non_emergency_line_share.value

TIMEZONE = ZoneInfo("America/New_York")


def coverage(weekdays, start_hour: int, end_hour: int) -> float:
    """Share of calls arriving during shifts that start on `weekdays` (0=Mon)
    and run over [start_hour, end_hour). An end_hour above 24 runs past
    midnight (26 = 2 AM), and those hours fall on the following weekday.

    Assumes hour of day and day of week are independent.
    """
    same_day = sum(HOUR_WEIGHTS[start_hour:min(end_hour, 24)])
    next_day = sum(HOUR_WEIGHTS[:max(0, end_hour - 24)])

    return sum(
        DAY_WEIGHTS[day] * same_day + DAY_WEIGHTS[(day + 1) % 7] * next_day
        for day in set(weekdays)
    )


def duration_multiplier(rng: random.Random, cv: float = 0.5) -> float:
    """Lognormal multiplier on average call duration (mean 1, coefficient of
    variation `cv`), clipped to 0.25-4, so the mean lands just under 1."""
    sigma = math.sqrt(math.log(1 + cv**2))
    return min(4.0, max(0.25, rng.lognormvariate(-sigma**2 / 2, sigma)))


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth's method; fine for the small daily rates used here.
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def generate_calls(
    rng: random.Random,
    start_day: date,
    weeks: int,
    calls_per_week: float = CALLS_PER_WEEK,
) -> list[Incident]:
    """Arrivals sorted by time, with all four safety answers False.

    The weekly volume is a count of community-responder-appropriate calls,
    i.e. calls that have already passed the safety questions, so every
    generated call has all four answers False.
    """
    types, type_weights = zip(*CALL_TYPE_WEIGHTS, strict=True)
    calls = []

    for offset in range(7 * weeks):
        day = start_day + timedelta(days=offset)
        count = _poisson(rng, calls_per_week * DAY_WEIGHTS[day.weekday()])

        for _ in range(count):
            hour = rng.choices(range(24), HOUR_WEIGHTS)[0]
            calls.append(
                Incident(
                    call_type=rng.choices(types, type_weights)[0],
                    weapon_present=False,
                    violence=False,
                    injury=False,
                    immediate_danger=False,
                    timestamp=datetime(
                        day.year, day.month, day.day, hour,
                        rng.randrange(60), rng.randrange(60),
                        tzinfo=TIMEZONE,
                    ),
                )
            )

    return sorted(calls, key=lambda c: c.timestamp)
