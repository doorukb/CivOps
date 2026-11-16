from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


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
    source_line: str | None = None

    evidence: dict[str, str] = Field(default_factory=dict)

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
    transcript: str | None = None

class AuditRecord(BaseModel):
    call_id: str
    incident: Incident
    actual_destination: Destination
    transcript: str | None = None  # scanned by the tripwires when present

class AuditRequest(BaseModel):
    records: list[AuditRecord]

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
    speaker: str
    text: str
    is_final: bool
    t: float = Field(ge=0)