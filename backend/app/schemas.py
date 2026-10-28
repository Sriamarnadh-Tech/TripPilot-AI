from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------
# TRIP REQUEST
# ---------------------------------------------------------

class TripRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=150)

    startDate: date
    endDate: date

    budget: float = Field(gt=0)

    travelers: int = Field(ge=1, le=10)

    interests: list[str] = Field(default_factory=list)

    travelStyle: str = "Balanced"

    @model_validator(mode="after")
    def validate_dates(self):
        if self.endDate < self.startDate:
            raise ValueError(
                "endDate must be on or after startDate"
            )

        if (self.endDate - self.startDate).days > 30:
            raise ValueError(
                "Trip length cannot exceed 31 days"
            )

        return self


# ---------------------------------------------------------
# EVIDENCE INPUT
# ---------------------------------------------------------

class EvidenceInput(BaseModel):
    """
    Represents a report about a possible travel disruption.

    Confidence is the confidence reported or assigned to this
    individual report. It is not automatically the probability
    that the disruption is genuinely occurring.
    """

    disruption_type: Literal[
        "weather",
        "closure",
        "transport",
    ]

    affected_day: int = Field(
        ge=1,
        le=31,
    )

    affected_activity_index: int = Field(
        default=0,
        ge=0,
        le=2,
    )

    source: str = Field(
        min_length=1,
        max_length=200,
    )

    # Optional stable identifier for source tracking.
    source_id: str | None = Field(
        default=None,
        max_length=200,
    )

    # Reports originating from the same underlying source can
    # share a provenance group to avoid false corroboration.
    provenance_group: str | None = Field(
        default=None,
        max_length=200,
    )

    observed_at: str

    valid_until: str | None = None

    confidence: float = Field(
        ge=0,
        le=1,
    )

    # Neutral prototype default. This value is not a calibrated
    # reliability estimate unless supported by historical data.
    source_reliability: float = Field(
        default=0.5,
        ge=0,
        le=1,
    )

    claim: str = Field(
        min_length=1,
        max_length=500,
    )

    corroborating_sources: list[str] = Field(
        default_factory=list,
        max_length=20,
    )

    conflicting_claims: list[str] = Field(
        default_factory=list,
        max_length=20,
    )


# ---------------------------------------------------------
# EVIDENCE ASSESSMENT RESPONSE
# ---------------------------------------------------------

class EvidenceComponents(BaseModel):
    reported_confidence: float = Field(
        ge=0,
        le=1,
    )

    source_reliability: float = Field(
        ge=0,
        le=1,
    )

    recency_score: float = Field(
        ge=0,
        le=1,
    )

    corroboration_score: float = Field(
        ge=0,
        le=1,
    )

    evidence_score: float = Field(
        ge=0,
        le=1,
    )

    age_hours: float

    corroborating_source_count: int = Field(
        ge=0,
    )

    conflict_count: int = Field(
        ge=0,
    )


class EvidenceAssessment(BaseModel):
    status: Literal[
        "strong_evidence",
        "uncertain",
        "weak_evidence",
        "conflicting",
        "expired",
        "invalid_timestamp",
        "invalid_validity_window",
    ]

    decision: Literal[
        "retain",
        "verify",
        "warn",
        "repair",
    ]

    reason: str

    components: EvidenceComponents


# ---------------------------------------------------------
# DISRUPTION DECISION
# ---------------------------------------------------------

class DisruptionAction(BaseModel):
    """
    Structured decision produced by the evidence policy.
    """

    action: Literal[
        "retain",
        "verify",
        "warn",
        "repair",
    ]

    reason: str

    evidence_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    affected_day: int = Field(
        ge=1,
        le=31,
    )

    affected_activity_index: int = Field(
        ge=0,
        le=2,
    )

    requires_human_confirmation: bool = False


# ---------------------------------------------------------
# REPLANNING REQUEST
# ---------------------------------------------------------

class ReplanRequest(BaseModel):
    trip_id: str

    evidence: EvidenceInput


# ---------------------------------------------------------
# BUDGET UPDATE
# ---------------------------------------------------------

class BudgetUpdateRequest(BaseModel):
    trip_id: str

    new_budget: float = Field(
        gt=0,
    )