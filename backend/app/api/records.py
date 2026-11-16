"""The call log: dispatcher reviews, and read access to stored calls."""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from starlette.responses import Response

from app.models import (
    CALL_ID_PATTERN,
    MAX_TRANSCRIPT_CHARS,
    Destination,
    Incident,
)
from app.services.rule_engine import evaluate_incident
from app.services.store import get_store

router = APIRouter(tags=["Call Log"])


class ReviewRequest(BaseModel):
    """What the dispatcher did with a recommendation.

    The request carries the facts, not the recommendation: the server
    re-evaluates the incident itself, so the log can never contain a
    recommendation the rulebook did not actually make.
    """

    call_id: str | None = Field(default=None, pattern=CALL_ID_PATTERN)
    incident: Incident
    # Used only to re-run the tripwire. Never stored by this endpoint.
    transcript: str | None = Field(default=None, max_length=MAX_TRANSCRIPT_CHARS)
    action: Literal["confirmed", "overridden"]
    chosen_destination: Destination | None = None
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def override_needs_destination_and_reason(self):
        self.reason = self.reason.strip()
        if self.action == "overridden":
            if self.chosen_destination is None:
                raise ValueError("An override must say which destination was chosen")
            if len(self.reason) < 3:
                raise ValueError("An override must give a reason")
        return self


class ReviewRecord(BaseModel):
    id: int
    created_at: str
    call_id: str
    call_source: str
    action: str
    rule_id: str
    recommended_destination: str
    chosen_destination: str
    reason: str
    rulebook_version: str | None
    simulated_time: str | None


@router.post("/reviews", response_model=ReviewRecord, status_code=201)
def record_review(request: ReviewRequest):
    decision = evaluate_incident(request.incident, transcript=request.transcript)
    recommended = decision.destination

    if request.action == "confirmed":
        if request.chosen_destination not in (None, recommended):
            raise HTTPException(
                status_code=422,
                detail="A confirmation cannot choose a different destination; use an override",
            )
        if decision.provisional:
            # Autonomy in one direction only: lowering urgency takes a person.
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "This recommendation is provisional: a person must confirm "
                        "the AI-proposed 'no' answers before it can be accepted."
                    ),
                    "needs_confirmation": decision.needs_confirmation,
                },
            )
        chosen = recommended
    else:
        chosen = request.chosen_destination
        if chosen == recommended:
            raise HTTPException(
                status_code=422,
                detail="An override must choose a destination other than the recommended one",
            )

    # A typed or pasted transcript has no call yet; give the review one to hang on.
    call_id = request.call_id or f"manual-{uuid.uuid4().hex}"

    return get_store().record_review(
        call_id=call_id,
        incident=request.incident,
        decision=decision,
        action=request.action,
        chosen_destination=chosen.value,
        reason=request.reason,
    )


@router.get("/reviews", response_model=list[ReviewRecord])
def list_reviews(limit: int = Query(50, ge=1, le=500)):
    """Most recent dispatcher reviews, newest first."""
    return get_store().reviews(limit)


@router.get("/reviews.csv")
def export_reviews():
    """The whole review log as CSV, oldest first."""
    return Response(
        content=get_store().reviews_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="despatch-reviews.csv"'},
    )


@router.get("/calls")
def list_calls(limit: int = Query(50, ge=1, le=500)):
    """Stored calls, newest first."""
    return get_store().calls(limit)


@router.get("/calls/{call_id}")
def get_call(call_id: str):
    """One call with its stored transcript (scripted calls only, unless
    DESPATCH_STORE_LIVE_TRANSCRIPTS=1), decisions and reviews."""
    call = get_store().call(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Unknown call")
    return call
