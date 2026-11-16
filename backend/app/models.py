from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

# Request-size limits. This is a localhost demo, but an unbounded body is still
# an easy way to pin a CPU, so every free-text field and list has a ceiling.
MAX_TRANSCRIPT_CHARS = 20_000
MAX_EVENT_TEXT_CHARS = 2_000
MAX_AUDIT_RECORDS = 5_000
MAX_SIMULATION_INCIDENTS = 20_000


class CallType(StrEnum):
    WELLBEING_CHECK = "wellbeing_check"
    DISTURBANCE = "disturbance"
    SUSPICIOUS = "suspicious"
    NOISE_COMPLAINT = "noise_complaint"
    OTHER = "other"


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

    @field_validator("evidence")
    @classmethod
    def bound_evidence(cls, evidence: dict[str, str]) -> dict[str, str]:
        for field, quote in evidence.items():
            if len(field) > 64 or len(quote) > MAX_EVENT_TEXT_CHARS:
                raise ValueError("evidence entry is too long")
        return evidence


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
    source: str | None = None


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

class SimulationConfig(BaseModel):
    start_hour: int = Field(default=8, ge=0, le=23)
    end_hour: int = Field(default=16, ge=1, le=24)
    teams: int = Field(default=3, ge=1, le=20)
    average_duration_minutes: int = Field(
        default=60, ge=5, le=240
    )
    include_weekends: bool = False
    include_noise_complaints: bool = False

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.end_hour <= self.start_hour:
            raise ValueError(
                "end_hour must be greater than start_hour"
            )
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
