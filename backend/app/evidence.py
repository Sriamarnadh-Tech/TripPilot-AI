from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, List


# Prototype thresholds, not empirically calibrated probabilities.
REPAIR_THRESHOLD = 0.78
VERIFY_THRESHOLD = 0.45

# Recency decay: evidence receives a lower recency score as it ages.
# This is a configurable prototype assumption, not a learned parameter.
RECENCY_HALF_LIFE_HOURS = 6.0


def _parse_timestamp(value: str, field_name: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO-8601 timestamp.")

    try:
        normalized = value.strip()

        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"

        parsed = datetime.fromisoformat(normalized)

    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a valid ISO-8601 timestamp."
        ) from exc

    if parsed.tzinfo is None:
        # Naive timestamps are interpreted as UTC for this prototype.
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _bounded_score(value: Any, field_name: str) -> float:
    """Validate a numeric score in the range [0, 1]."""

    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc

    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1.")

    return score


def _recency_score(
    observed_at: datetime,
    now: datetime,
) -> float:
    """Calculate an exponential recency score."""

    age_hours = max(
        0.0,
        (now - observed_at).total_seconds() / 3600.0,
    )

    return exp(
        -0.6931471805599453
        * age_hours
        / RECENCY_HALF_LIFE_HOURS
    )


def _unique_sources(
    evidence: Dict[str, Any],
) -> List[str]:
    """
    Collect distinct corroborating sources.

    Exclude the primary source from the corroboration count.
    The input cannot independently establish whether sources
    are genuinely independent; that requires provenance data.
    """

    primary = str(evidence.get("source", "")).strip()

    sources = evidence.get("corroborating_sources") or []

    if not isinstance(sources, list):
        raise ValueError("corroborating_sources must be a list.")

    unique = set()

    for source in sources:
        if not isinstance(source, str):
            continue

        source = source.strip()

        if source and source != primary:
            unique.add(source)

    return sorted(unique)


def assess_evidence(
    evidence: Dict[str, Any],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """
    Assess disruption evidence and recommend an action.

    Canonical actions:
        retain
        verify
        warn
        repair

    The evidence score is a transparent heuristic, not a calibrated
    probability that a disruption is genuine.

    Required fields:
        source
        observed_at
        confidence

    Optional fields:
        valid_until
        source_reliability
        corroborating_sources
        conflicting_claims
        claim
    """

    if not isinstance(evidence, dict):
        raise ValueError("Evidence must be provided as a dictionary.")

    if now is None:
        now = datetime.now(timezone.utc)
    elif not isinstance(now, datetime):
        raise ValueError("'now' must be a datetime object.")

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)

    source = evidence.get("source")

    if not isinstance(source, str) or not source.strip():
        raise ValueError("Evidence source must be a non-empty string.")

    confidence = _bounded_score(
        evidence.get("confidence"),
        "confidence",
    )

    # Until historical data is available, use an explicit neutral
    # default instead of silently treating every source as reliable.
    source_reliability = _bounded_score(
        evidence.get("source_reliability", 0.5),
        "source_reliability",
    )

    observed_at = _parse_timestamp(
        evidence.get("observed_at"),
        "observed_at",
    )

    valid_until_value = evidence.get("valid_until")

    valid_until = (
        _parse_timestamp(valid_until_value, "valid_until")
        if valid_until_value
        else None
    )

    corroborating_sources = _unique_sources(evidence)

    conflicting_claims = evidence.get("conflicting_claims") or []

    if not isinstance(conflicting_claims, list):
        raise ValueError("conflicting_claims must be a list.")

    age_hours = (
        now - observed_at
    ).total_seconds() / 3600.0

    recency = _recency_score(observed_at, now)

    # Multiple listed sources increase the corroboration component,
    # with diminishing returns. This does not prove independence.
    corroboration = min(
        1.0,
        len(corroborating_sources) / 2.0,
    )

    # Transparent heuristic. Keep the components separate so that
    # future experiments can ablate and compare them.
    evidence_score = (
        0.40 * confidence
        + 0.25 * source_reliability
        + 0.20 * recency
        + 0.15 * corroboration
    )

    evidence_score = round(evidence_score, 4)

    components = {
        "reported_confidence": round(confidence, 4),
        "source_reliability": round(source_reliability, 4),
        "recency_score": round(recency, 4),
        "corroboration_score": round(corroboration, 4),
        "evidence_score": evidence_score,
        "age_hours": round(age_hours, 2),
        "corroborating_source_count": len(corroborating_sources),
        "conflict_count": len(conflicting_claims),
    }

    # Conservative handling of evidence that cannot be trusted
    # temporally, even if the report claims high confidence.
    # Reject reports that claim to originate in the future.
    if observed_at > now:
        return {
        "status": "invalid_timestamp",
        "decision": "verify",
        "reason": "The report timestamp is in the future.",
        "components": components,
    }

# Reject logically impossible validity windows first.
    if valid_until is not None and valid_until < observed_at:
        return {
        "status": "invalid_validity_window",
        "decision": "verify",
        "reason": "The report expires before its observation timestamp.",
        "components": components,
    }

# Do not rely on reports that are no longer valid.
    if valid_until is not None and valid_until < now:
        return {
        "status": "expired",
        "decision": "verify",
        "reason": (
            "The evidence validity window has expired. "
            "Retrieve current information before repairing the plan."
        ),
        "components": components,
    }

    if conflicting_claims:
        return {
            "status": "conflicting",
            "decision": "warn",
            "reason": (
                "Conflicting claims exist. Do not automatically repair "
                "the itinerary until the conflict is assessed."
            ),
            "components": components,
        }

    if evidence_score >= REPAIR_THRESHOLD:
        return {
            "status": "strong_evidence",
            "decision": "repair",
            "reason": (
                "The prototype evidence score passed the configured "
                "repair threshold."
            ),
            "components": components,
        }

    if evidence_score >= VERIFY_THRESHOLD:
        return {
            "status": "uncertain",
            "decision": "verify",
            "reason": (
                "Evidence is not strong enough for automatic repair. "
                "Seek additional current information."
            ),
            "components": components,
        }

    return {
        "status": "weak_evidence",
        "decision": "retain",
        "reason": (
            "Evidence is weak and uncorroborated. Retain the itinerary "
            "for now, while continuing to monitor for updates."
        ),
        "components": components,
    }