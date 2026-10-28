"""
Reproducible synthetic tests for AdaptiveTrip's evidence assessment policy.

Important:
- These are handcrafted policy checks, not a real-world performance estimate.
- Passing these tests verifies expected behavior on selected cases only.
- Evidence scores are heuristic scores, not calibrated probabilities.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .evidence import assess_evidence


# Fixed timestamp makes the test scenarios reproducible.
EVALUATION_TIME = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def make_evidence(
    *,
    confidence: float = 0.5,
    corroborating_sources: list[str] | None = None,
    conflicting_claims: list[str] | None = None,
    observed_at: datetime | None = None,
    valid_until: datetime | None = None,
    source_reliability: float = 0.5,
) -> dict[str, Any]:
    """Create a synthetic evidence report."""

    if observed_at is None:
        observed_at = EVALUATION_TIME - timedelta(hours=1)

    if valid_until is None:
        valid_until = EVALUATION_TIME + timedelta(hours=3)

    return {
        "disruption_type": "weather",
        "affected_day": 1,
        "affected_activity_index": 0,
        "source": "synthetic_primary_source",
        "observed_at": observed_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "confidence": confidence,
        "source_reliability": source_reliability,
        "claim": "Synthetic disruption report for policy testing.",
        "corroborating_sources": corroborating_sources or [],
        "conflicting_claims": conflicting_claims or [],
    }


def build_scenarios() -> list[dict[str, Any]]:
    """Build deterministic scenarios with explicitly expected actions."""

    return [
        {
            "name": "strong_recent_evidence",
            "description": "Recent report with high confidence and reliability.",
            "evidence": make_evidence(
                confidence=0.95,
                source_reliability=0.95,
            ),
            "expected_action": "repair",
        },
        {
            "name": "corroborated_evidence",
            "description": "Moderately strong report with independent-looking corroboration.",
            "evidence": make_evidence(
                confidence=0.70,
                source_reliability=0.80,
                corroborating_sources=["synthetic_source_b", "synthetic_source_c"],
            ),
            "expected_action": "repair",
        },
        {
            "name": "weak_evidence",
            "description": "Low-confidence report with low source reliability.",
            "evidence": make_evidence(
                confidence=0.10,
                source_reliability=0.10,
            ),
            "expected_action": "retain",
        },
        {
            "name": "conflicting_evidence",
            "description": "A report has at least one explicitly conflicting claim.",
            "evidence": make_evidence(
                confidence=0.95,
                source_reliability=0.95,
                conflicting_claims=["Another source reports normal conditions."],
            ),
            "expected_action": "warn",
        },
        {
            "name": "expired_evidence",
            "description": "Evidence validity window ended before evaluation time.",
            "evidence": make_evidence(
                confidence=0.99,
                source_reliability=0.99,
                valid_until=EVALUATION_TIME - timedelta(minutes=1),
            ),
            "expected_action": "verify",
        },
        {
            "name": "uncertain_evidence",
            "description": "Evidence score falls into the verification range.",
            "evidence": make_evidence(
                confidence=0.45,
                source_reliability=0.50,
            ),
            "expected_action": "verify",
        },
        {
            "name": "future_dated_evidence",
            "description": "Observation timestamp is later than evaluation time.",
            "evidence": make_evidence(
                confidence=0.95,
                source_reliability=0.95,
                observed_at=EVALUATION_TIME + timedelta(hours=1),
            ),
            "expected_action": "verify",
        },
        {
            "name": "invalid_observation_timestamp",
            "description": "Observation timestamp cannot be parsed.",
            "evidence": {
                **make_evidence(confidence=0.90),
                "observed_at": "not-a-valid-timestamp",
            },
            "expected_action": "verify",
        },
    ]


def evaluate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Run the policy and compare its behavior with the expected result."""

    try:
        assessment = assess_evidence(
            scenario["evidence"],
            now=EVALUATION_TIME,
        )

        predicted_action = assessment["decision"]
        components = assessment.get("components", {})

        return {
            "scenario": scenario["name"],
            "description": scenario["description"],
            "expected_action": scenario["expected_action"],
            "predicted_action": predicted_action,
            "correct": predicted_action == scenario["expected_action"],
            "reason": assessment.get("reason", ""),
            "evidence_components": components,
            "error": None,
        }

    except ValueError as exc:
        # Invalid timestamps are expected to fail input validation.
        if scenario["name"] == "invalid_observation_timestamp":
            return {
                "scenario": scenario["name"],
                "description": scenario["description"],
                "expected_action": "reject_invalid_input",
                "predicted_action": "reject_invalid_input",
                "correct": True,
                "reason": "Invalid timestamp rejected by input validation.",
                "evidence_components": {},
                "error": str(exc),
            }

        return {
            "scenario": scenario["name"],
            "description": scenario["description"],
            "expected_action": scenario["expected_action"],
            "predicted_action": None,
            "correct": False,
            "reason": "",
            "evidence_components": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    except Exception as exc:
        return {
            "scenario": scenario["name"],
            "description": scenario["description"],
            "expected_action": scenario["expected_action"],
            "predicted_action": None,
            "correct": False,
            "reason": "",
            "evidence_components": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate descriptive metrics for the synthetic test set."""

    total = len(results)
    correct_count = sum(result["correct"] for result in results)

    expected_counts = Counter(
        result["expected_action"] for result in results
    )
    predicted_counts = Counter(
        result["predicted_action"]
        for result in results
        if result["predicted_action"] is not None
    )

    actions = ["retain", "verify", "warn", "repair"]

    confusion_matrix = {
        expected: {
            predicted: sum(
                result["expected_action"] == expected
                and result["predicted_action"] == predicted
                for result in results
            )
            for predicted in actions
        }
        for expected in actions
    }

    return {
        "scenario_count": total,
        "correct_count": correct_count,
        "incorrect_count": total - correct_count,
        "decision_accuracy": (
            correct_count / total if total else 0.0
        ),
        "expected_action_counts": dict(expected_counts),
        "predicted_action_counts": dict(predicted_counts),
        "confusion_matrix": confusion_matrix,
    }


def run() -> dict[str, Any]:
    """Run all scenarios, save the report, and return the results."""

    scenarios = build_scenarios()
    results = [
        evaluate_scenario(scenario)
        for scenario in scenarios
    ]

    metrics = calculate_metrics(results)

    output = {
        "evaluation_name": "TripPilot Evidence Policy Synthetic Checks",
        "evaluation_timestamp": EVALUATION_TIME.isoformat(),
        "evaluation_type": "handcrafted_synthetic_policy_checks",
        "metrics": metrics,
        "results": results,
        "limitations": [
            "The scenarios are handcrafted and are not representative "
            "of a measured real-world distribution.",
            "Decision accuracy on this small test set is not evidence "
            "of real-world disruption-detection performance.",
            "Evidence scores are heuristic values, not calibrated "
            "probabilities.",
            "Corroboration independence is not established merely by "
            "using different source names.",
            "This evaluator does not measure itinerary feasibility, "
            "budget preservation, missed real disruptions, or "
            "unnecessary repairs on a representative dataset.",
        ],
    }

    output_path = (
        Path(__file__).resolve().parent.parent
        / "evaluation_results.json"
    )

    output_path.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(output, indent=2))
    print(f"\nSaved evaluation report: {output_path}")

    if metrics["incorrect_count"] > 0:
        raise AssertionError(
            f"{metrics['incorrect_count']} of "
            f"{metrics['scenario_count']} synthetic scenarios failed. "
            f"Inspect {output_path}."
        )

    print("\nAll synthetic policy checks passed.")
    return output


if __name__ == "__main__":
    run()