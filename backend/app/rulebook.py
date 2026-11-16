"""The rulebook as typed, validated, immutable data.

`rules/dispatch.yaml` is parsed once, checked against these models and cached.
A typo in the YAML (an unknown condition key, a duplicate rule ID, a schedule
that ends before it starts) fails loudly at load instead of silently never
matching a call.

The models also enforce the project's safety invariants on the *file itself*,
so they cannot be edited away by accident:

* every safety outcome (tripwire, a reported safety concern, incomplete
  screening, missing context) ends in ``human_review``;
* an eligibility rule may only send a call to CRESS, to CRESS follow-up or to
  a human. No rule can route to police, fire/EMS or a crisis line.
"""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models import (
    MAX_END_HOUR,
    SAFETY_FIELDS,
    CallType,
    Destination,
    check_shift_hours,
)

RULEBOOK_PATH = Path(__file__).resolve().parents[1] / "rules" / "dispatch.yaml"

# Where a rule is allowed to send a call. The other Destination values exist
# to describe what dispatch *actually did* in audit records; they are reserved
# and no recommendation can produce them.
ROUTABLE_DESTINATIONS = frozenset(
    {Destination.CRESS, Destination.CRESS_FOLLOWUP, Destination.HUMAN_REVIEW}
)

SAFETY_FIELD_CHOICES = frozenset(SAFETY_FIELDS)


class RulebookError(ValueError):
    """The rulebook file is missing, unreadable or fails validation."""


class _Frozen(BaseModel):
    # frozen: the cached rulebook is shared by every request, so nobody may
    # mutate it in place. extra="forbid": a misspelled key is an error.
    model_config = ConfigDict(frozen=True, extra="forbid")


class SafetyOutcome(_Frozen):
    """A fixed outcome of the safety stages. Always a human."""

    id: str = Field(min_length=1)
    destination: Destination
    reason: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def must_go_to_a_human(self):
        if self.destination is not Destination.HUMAN_REVIEW:
            raise ValueError(
                f"{self.id}: a safety outcome must go to human_review, "
                f"not {self.destination.value}"
            )
        return self


class Screening(_Frozen):
    safety_fields: tuple[str, ...] = Field(min_length=1)
    tripwire: SafetyOutcome
    escalation: SafetyOutcome
    incomplete: SafetyOutcome
    context_incomplete: SafetyOutcome

    @model_validator(mode="after")
    def safety_fields_exist(self):
        unknown = set(self.safety_fields) - SAFETY_FIELD_CHOICES
        if unknown:
            raise ValueError(f"unknown safety fields: {sorted(unknown)}")
        if len(set(self.safety_fields)) != len(self.safety_fields):
            raise ValueError("safety_fields contains duplicates")
        return self


class Schedule(_Frozen):
    """When CRESS is on duty. Hours are local to `timezone`."""

    timezone: str
    weekdays: tuple[int, ...]  # Monday=0 ... Sunday=6: the days a shift STARTS
    start_hour: int = Field(ge=0, le=23)
    # Above 24 the shift runs past midnight: 26 means 2 AM the next day.
    end_hour: int = Field(ge=1, le=MAX_END_HOUR)

    @model_validator(mode="after")
    def check(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown timezone: {self.timezone}") from error
        if any(day not in range(7) for day in self.weekdays):
            raise ValueError("weekdays must be between 0 (Monday) and 6 (Sunday)")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("weekdays contains duplicates")
        check_shift_hours(self.start_hour, self.end_hour)
        return self

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class Conditions(_Frozen):
    """Facts a rule can test. Leave one out and the rule ignores that fact."""

    eligible_call_type: bool | None = None
    on_duty: bool | None = None

    def matches(self, facts: dict[str, bool]) -> bool:
        return all(
            facts[name] == expected
            for name, expected in self.model_dump(exclude_none=True).items()
        )


class Rule(_Frozen):
    id: str = Field(min_length=1)
    priority: int = Field(ge=1)  # lower number wins
    conditions: Conditions
    destination: Destination
    reason: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def destination_is_routable(self):
        if self.destination not in ROUTABLE_DESTINATIONS:
            raise ValueError(
                f"{self.id}: rules may only route to "
                f"{sorted(d.value for d in ROUTABLE_DESTINATIONS)}; "
                f"{self.destination.value} is reserved"
            )
        return self


class Rulebook(_Frozen):
    version: str = Field(min_length=1)
    screening: Screening
    schedule: Schedule
    eligible_call_types: tuple[CallType, ...]
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ids_are_unique(self):
        ids = [rule.id for rule in self.rules] + [
            outcome.id for outcome in self.safety_outcomes()
        ]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule ids: {duplicates}")
        if len(set(self.eligible_call_types)) != len(self.eligible_call_types):
            raise ValueError("eligible_call_types contains duplicates")
        return self

    def safety_outcomes(self) -> tuple[SafetyOutcome, ...]:
        screening = self.screening
        return (
            screening.tripwire,
            screening.escalation,
            screening.incomplete,
            screening.context_incomplete,
        )

    def with_changes(
        self,
        *,
        schedule: dict | None = None,
        eligible_call_types: tuple[CallType, ...] | None = None,
    ) -> "Rulebook":
        """A validated copy with a different schedule and/or eligibility list.

        The What-If simulator uses this to try a proposed schedule without
        touching the shared rulebook.
        """
        data = self.model_dump()
        if schedule:
            data["schedule"] = {**data["schedule"], **schedule}
        if eligible_call_types is not None:
            data["eligible_call_types"] = eligible_call_types
        return Rulebook.model_validate(data)


def parse_rulebook(text: str) -> Rulebook:
    """Parse and validate rulebook YAML. Raises RulebookError with the reason."""
    try:
        return Rulebook.model_validate(yaml.safe_load(text))
    except (yaml.YAMLError, ValidationError) as error:
        raise RulebookError(f"Invalid rulebook: {error}") from error


@lru_cache(maxsize=1)
def load_rulebook() -> Rulebook:
    """The shipped rulebook, read and validated once per process.

    The result is immutable, so sharing one instance is safe. To pick up an
    edited file without restarting, call `load_rulebook.cache_clear()`.
    """
    try:
        text = RULEBOOK_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise RulebookError(f"Cannot read rulebook: {error}") from error
    return parse_rulebook(text)
