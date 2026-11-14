from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CallType(str, Enum):
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

class Destination(str, Enum):
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
    