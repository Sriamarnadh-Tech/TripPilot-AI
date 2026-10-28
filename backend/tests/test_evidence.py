from datetime import datetime, timedelta, timezone

from app.evidence import assess_evidence


def make_evidence(
    confidence=0.95,
    reliability=1.0,
    corroborating_sources=None,
    conflicting_claims=None,
    expired=False,
):
    now = datetime.now(timezone.utc)

    observed_at = now - timedelta(hours=1)

    valid_until = (
        now - timedelta(minutes=1)
        if expired
        else now + timedelta(hours=1)
    )

    return {
        "disruption_type": "closure",
        "affected_day": 1,
        "affected_activity_index": 0,
        "source": "test_source",
        "observed_at": observed_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "confidence": confidence,
        "source_reliability": reliability,
        "claim": "The attraction is closed.",
        "corroborating_sources": corroborating_sources or [],
        "conflicting_claims": conflicting_claims or [],
    }


def test_strong_evidence_recommends_repair():
    evidence = make_evidence(
        confidence=0.95,
        reliability=1.0,
        corroborating_sources=["source_b", "source_c"],
    )

    result = assess_evidence(evidence)

    assert result["decision"] == "repair"
    assert result["status"] == "strong_evidence"


def test_conflicting_evidence_recommends_warning():
    evidence = make_evidence(
        conflicting_claims=["Another source reports normal access."]
    )

    result = assess_evidence(evidence)

    assert result["decision"] == "warn"
    assert result["status"] == "conflicting"


def test_expired_evidence_requires_verification():
    evidence = make_evidence(expired=True)

    result = assess_evidence(evidence)

    assert result["decision"] == "verify"
    assert result["status"] == "expired"


def test_weak_evidence_retains_itinerary():
    evidence = make_evidence(
        confidence=0.1,
        reliability=0.2,
    )

    result = assess_evidence(evidence)

    assert result["decision"] == "retain"
    assert result["status"] == "weak_evidence"


def test_future_timestamp_requires_verification():
    evidence = make_evidence()

    evidence["observed_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).isoformat()

    result = assess_evidence(evidence)

    assert result["decision"] == "verify"
    assert result["status"] == "invalid_timestamp"


def test_impossible_validity_window_is_rejected():
    now = datetime.now(timezone.utc)

    evidence = make_evidence()

    evidence["observed_at"] = (
        now - timedelta(hours=1)
    ).isoformat()

    evidence["valid_until"] = (
        now - timedelta(hours=2)
    ).isoformat()

    result = assess_evidence(evidence)

    assert result["decision"] == "verify"
    assert result["status"] == "invalid_validity_window"


def test_invalid_confidence_is_rejected():
    evidence = make_evidence()
    evidence["confidence"] = 1.5

    try:
        assess_evidence(evidence)
        assert False, "Expected invalid confidence to raise ValueError"
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)


def test_duplicate_sources_are_not_double_counted():
    evidence = make_evidence(
        corroborating_sources=[
            "source_b",
            "source_b",
            "source_b",
        ]
    )

    result = assess_evidence(evidence)

    assert result["components"]["corroborating_source_count"] == 1