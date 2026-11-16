from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Request-size limits. This is a localhost demo, but an unbounded body is still
# an easy way to pin a CPU, so every free-text field and list has a ceiling.
MAX_TRANSCRIPT_CHARS = 20_000
MAX_EVENT_TEXT_CHARS = 2_000
MAX_AUDIT_RECORDS = 5_000
MAX_SIMULATION_INCIDENTS = 20_000

# A call ID is an opaque token (a UUID in practice).
CALL_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class CallType(StrEnum):
    WELLBEING_CHECK = "wellbeing_check"
    DISTURBANCE = "disturbance"
    SUSPICIOUS = "suspicious"
    NOISE_COMPLAINT = "noise_complaint"
    OTHER = "other"


# The four screening answers. The order is the order they are asked and shown.
SAFETY_FIELDS = ("weapon_present", "violence", "injury", "immediate_danger")

# Who an answer comes from: the language model, or a person at the console.
Provenance = Literal["model", "human"]


class Incident(BaseModel):
    call_type: CallType | None = None

    weapon_present: bool | None = None
    violence: bool | None = None
    injury: bool | None = None
    immediate_danger: bool | None = None

    caller_requests_cress: bool | None = None

    timestamp: datetime | None = None
    source_line: str | None = Field(default=None, max_length=64)

    evidence: dict[str, str] = Field(default_factory=dict, max_length=16)

    # Which screening answers were proposed by the model and not yet confirmed
    # by a person. An answer with no entry is treated as human-entered, which
    # is the case for audit records, the simulator and hand-filled forms.
    provenance: dict[str, Provenance] = Field(default_factory=dict)

    @field_validator("evidence")
    @classmethod
    def bound_evidence(cls, evidence: dict[str, str]) -> dict[str, str]:
        for field, quote in evidence.items():
            if len(field) > 64 or len(quote) > MAX_EVENT_TEXT_CHARS:
                raise ValueError("evidence entry is too long")
        return evidence

    @field_validator("provenance")
    @classmethod
    def provenance_is_for_safety_fields(cls, provenance: dict) -> dict:
        unknown = set(provenance) - set(SAFETY_FIELDS)
        if unknown:
            raise ValueError(f"provenance is only tracked for {SAFETY_FIELDS}")
        return provenance

    def unconfirmed_negatives(self) -> list[str]:
        """Screening answers that are "no" only because the model said so."""
        return [
            field for field in SAFETY_FIELDS
            if getattr(self, field) is False and self.provenance.get(field) == "model"
        ]


class Destination(StrEnum):
    CRESS = "cress"
    POLICE = "police"
    FIRE_EMS = "fire_ems"
    CRISIS = "crisis"
    CRESS_FOLLOWUP = "cress_followup"
    HUMAN_REVIEW = "human_review"


class Decision(BaseModel):
    destination: Destination
    rule_id: str
    reason: str
    missing_information: list[str] = Field(default_factory=list)

    eligible: bool | None = None
    on_duty: bool | None = None
    # Where the rule comes from, and which rulebook version produced this.
    source: str | None = None
    rulebook_version: str | None = None

    # Autonomy in one direction only. The system may raise urgency by itself,
    # but a recommendation that sends a call AWAY from a human dispatcher is
    # provisional while any "no" it rests on was proposed by the model and not
    # confirmed by a person. The destination and rule are unchanged; a
    # provisional recommendation simply cannot be confirmed yet.
    provisional: bool = False
    needs_confirmation: list[str] = Field(default_factory=list)


class EvaluationRequest(BaseModel):
    incident: Incident
    transcript: str | None = Field(default=None, max_length=MAX_TRANSCRIPT_CHARS)


class AuditRecord(BaseModel):
    call_id: str = Field(min_length=1, max_length=64)
    incident: Incident
    actual_destination: Destination
    # Scanned by the tripwires when present.
    transcript: str | None = Field(default=None, max_length=MAX_TRANSCRIPT_CHARS)


class AuditRequest(BaseModel):
    records: list[AuditRecord] = Field(max_length=MAX_AUDIT_RECORDS)

# A shift may run past midnight: end_hour 26 means 2 AM the next day.
MAX_END_HOUR = 26


def check_shift_hours(start_hour: int, end_hour: int) -> None:
    """Shared by the rulebook schedule and the What-If simulator config."""
    if end_hour <= start_hour:
        raise ValueError("end_hour must be greater than start_hour")
    if end_hour > 24 and end_hour - 24 > start_hour:
        # e.g. 0 to 26: the hours after midnight would belong to two shifts.
        raise ValueError(
            "a shift that runs past midnight must end before the next one starts "
            f"(end_hour - 24 = {end_hour - 24} is later than start_hour = {start_hour})"
        )


class SimulationConfig(BaseModel):
    start_hour: int = Field(default=8, ge=0, le=23)
    end_hour: int = Field(
        default=16, ge=1, le=MAX_END_HOUR,
        description="Hour the shift ends. Above 24 means the next day (26 = 2 AM).",
    )
    teams: int = Field(default=3, ge=1, le=20)
    average_duration_minutes: int = Field(
        default=60, ge=5, le=240
    )
    include_weekends: bool = False
    include_noise_complaints: bool = False

    @model_validator(mode="after")
    def validate_schedule(self):
        check_shift_hours(self.start_hour, self.end_hour)
        return self


class SimulationResult(BaseModel):
    total_calls: int
    eligible_calls: int
    handled_calls: int
    missed_off_duty: int
    missed_busy: int
    utilization: float


class TranscriptEvent(BaseModel):
    speaker: str = Field(max_length=32)
    text: str = Field(max_length=MAX_EVENT_TEXT_CHARS)
    is_final: bool
    t: float = Field(ge=0)
    # Which call this event belongs to, so a late event from one call can
    # never be mistaken for part of the next.
    call_id: str | None = Field(default=None, pattern=CALL_ID_PATTERN)
