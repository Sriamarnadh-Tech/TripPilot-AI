"""
AdaptiveTrip: Synthetic baseline comparison benchmark.

This benchmark compares four disruption decision policies under
controlled report noise and source disagreement.

It is a synthetic experiment, not a real-world performance estimate.
The evidence-gated policy below is an experimental benchmark policy;
it does not modify or replace app.evidence.assess_evidence.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import exp
from pathlib import Path
from statistics import mean
from typing import Any


SEED = 42
SCENARIO_COUNT = 1000

# These are initial experimental parameters, not learned values.
REPAIR_THRESHOLD = 0.60
VERIFY_MARGIN = 0.15
RECENCY_HALF_LIFE_HOURS = 6.0

POLICIES = [
    "always_repair",
    "confidence_only",
    "majority_vote",
    "evidence_gated",
]


def generate_scenarios(
    count: int = SCENARIO_COUNT,
    seed: int = SEED,
) -> list[dict[str, Any]]:
    """
    Generate reproducible scenarios with known ground truth.

    Source reliability is predictive of report correctness.
    Confidence is also informative, but imperfect.

    This is a controlled simulation assumption, not a claim
    about real-world source reliability.
    """

    rng = random.Random(seed)
    scenarios = []

    for index in range(count):
        actual_disruption = rng.random() < 0.5

        report_count = rng.randint(1, 5)
        noise_level = rng.choice(["low", "medium", "high"])

        reports = []

        for report_index in range(report_count):

            # Source reliability distributions vary by noise level.
            if noise_level == "low":
                reliability = rng.uniform(0.80, 0.98)
            elif noise_level == "medium":
                reliability = rng.uniform(0.55, 0.85)
            else:
                reliability = rng.uniform(0.25, 0.70)

            # Reliability now predicts the probability of a correct report.
            report_is_wrong = (
                rng.random() > reliability
            )

            reported_disruption = (
                not actual_disruption
                if report_is_wrong
                else actual_disruption
            )

            # Correct reports tend to have higher confidence.
            # Incorrect reports can still have high confidence.
            # This represents imperfect confidence estimates.
            if report_is_wrong:
                confidence = rng.uniform(0.50, 0.85)
            else:
                confidence = rng.uniform(0.65, 0.98)

            # Simulate information becoming stale over time.
            age_hours = rng.uniform(0, 24)

            reports.append(
                {
                    "source": f"source_{report_index + 1}",
                    "claim": (
                        "disruption"
                        if reported_disruption
                        else "clear"
                    ),
                    "confidence": round(confidence, 4),
                    "source_reliability": round(reliability, 4),
                    "age_hours": round(age_hours, 2),
                    "report_is_wrong": report_is_wrong,
                }
            )

        claims = {
            report["claim"]
            for report in reports
        }

        scenarios.append(
            {
                "scenario_id": index + 1,
                "ground_truth_disruption": actual_disruption,
                "noise_level": noise_level,
                "reports": reports,
                "has_conflicting_reports": len(claims) > 1,
            }
        )

    return scenarios

def report_weight(
    report: dict[str, Any],
    *,
    use_confidence: bool = True,
    use_reliability: bool = True,
    use_recency: bool = True,
) -> float:
    """Calculate the evidence weight for one report."""

    confidence = (
        report["confidence"]
        if use_confidence
        else 1.0
    )

    reliability = (
        report["source_reliability"]
        if use_reliability
        else 1.0
    )

    if use_recency:
        recency = exp(
            -0.6931471805599453
            * report["age_hours"]
            / RECENCY_HALF_LIFE_HOURS
        )
    else:
        recency = 1.0

    return confidence * reliability * recency


def always_repair(scenario: dict[str, Any]) -> str:
    """Repair if any report claims a disruption."""

    if any(
        report["claim"] == "disruption"
        for report in scenario["reports"]
    ):
        return "repair"

    return "retain"


def confidence_only(scenario: dict[str, Any]) -> str:
    """Use confidence-weighted claims, ignoring other evidence factors."""

    disruption_weight = sum(
        report["confidence"]
        for report in scenario["reports"]
        if report["claim"] == "disruption"
    )

    clear_weight = sum(
        report["confidence"]
        for report in scenario["reports"]
        if report["claim"] == "clear"
    )

    total = disruption_weight + clear_weight

    if total == 0:
        return "verify"

    disruption_score = disruption_weight / total

    if disruption_score >= REPAIR_THRESHOLD:
        return "repair"

    if disruption_score >= REPAIR_THRESHOLD - VERIFY_MARGIN:
        return "verify"

    return "retain"


def majority_vote(scenario: dict[str, Any]) -> str:
    """Use the majority claim, verifying ties."""

    disruption_votes = sum(
        report["claim"] == "disruption"
        for report in scenario["reports"]
    )

    clear_votes = sum(
        report["claim"] == "clear"
        for report in scenario["reports"]
    )

    if disruption_votes > clear_votes:
        return "repair"

    if disruption_votes < clear_votes:
        return "retain"

    return "verify"


def evidence_gated(scenario: dict[str, Any]) -> str:
    """
    Combine confidence, source reliability, and report recency.

    Conflicting claims trigger verification unless the weighted
    evidence strongly favors one side.
    """

    disruption_weight = 0.0
    clear_weight = 0.0

    for report in scenario["reports"]:
        weight = report_weight(report)

        if report["claim"] == "disruption":
            disruption_weight += weight
        else:
            clear_weight += weight

    total = disruption_weight + clear_weight

    if total == 0:
        return "verify"

    disruption_score = disruption_weight / total
    has_conflict = scenario["has_conflicting_reports"]

    # Avoid automatic repair when reports conflict and neither side
    # has sufficiently strong weighted support.
    if has_conflict:
        if abs(disruption_score - 0.5) < VERIFY_MARGIN:
            return "verify"

    if disruption_score >= REPAIR_THRESHOLD:
        return "repair"

    if disruption_score >= REPAIR_THRESHOLD - VERIFY_MARGIN:
        return "verify"

    return "retain"


POLICY_FUNCTIONS = {
    "always_repair": always_repair,
    "confidence_only": confidence_only,
    "majority_vote": majority_vote,
    "evidence_gated": evidence_gated,
}


def evaluate_policy(
    policy_name: str,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate one policy against scenario ground truth."""

    decisions = []

    for scenario in scenarios:
        decision = POLICY_FUNCTIONS[policy_name](scenario)
        truth = scenario["ground_truth_disruption"]

        # For this benchmark, only repair counts as an intervention.
        # A verify or warn action is not treated as a successful repair.
        unnecessary_repair = (
            decision == "repair" and not truth
        )

        missed_disruption = (
            decision != "repair" and truth
        )

        correct_classification = (
            (decision == "repair") == truth
        )

        decisions.append(
            {
                "scenario_id": scenario["scenario_id"],
                "noise_level": scenario["noise_level"],
                "ground_truth_disruption": truth,
                "decision": decision,
                "correct_classification": correct_classification,
                "unnecessary_repair": unnecessary_repair,
                "missed_disruption": missed_disruption,
                "has_conflicting_reports": (
                    scenario["has_conflicting_reports"]
                ),
            }
        )

    total = len(decisions)

    if total == 0:
        raise ValueError("Cannot evaluate an empty scenario list.")

    unnecessary_count = sum(
        item["unnecessary_repair"]
        for item in decisions
    )

    missed_count = sum(
        item["missed_disruption"]
        for item in decisions
    )

    actual_disruptions = sum(
        item["ground_truth_disruption"]
        for item in decisions
    )

    actual_clear = total - actual_disruptions

    repairs = sum(
        item["decision"] == "repair"
        for item in decisions
    )

    correct = sum(
        item["correct_classification"]
        for item in decisions
    )

    return {
        "policy": policy_name,
        "scenario_count": total,
        "decision_accuracy": round(correct / total, 4),
        "unnecessary_repair_count": unnecessary_count,
        "unnecessary_repair_rate": round(
            unnecessary_count / actual_clear
            if actual_clear
            else 0.0,
            4,
        ),
        "missed_disruption_count": missed_count,
        "missed_disruption_rate": round(
            missed_count / actual_disruptions
            if actual_disruptions
            else 0.0,
            4,
        ),
        "repair_rate": round(repairs / total, 4),
        "details": decisions,
    }


def evaluate_by_noise(
    policy_name: str,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Report policy metrics separately for each noise level."""

    grouped = defaultdict(list)

    for scenario in scenarios:
        grouped[scenario["noise_level"]].append(scenario)

    output = {}

    for noise_level in ["low", "medium", "high"]:
        subset = grouped[noise_level]

        if subset:
            result = evaluate_policy(policy_name, subset)

            output[noise_level] = {
                "scenario_count": result["scenario_count"],
                "decision_accuracy": result["decision_accuracy"],
                "unnecessary_repair_rate": (
                    result["unnecessary_repair_rate"]
                ),
                "missed_disruption_rate": (
                    result["missed_disruption_rate"]
                ),
                "repair_rate": result["repair_rate"],
            }

    return output


def run_benchmark() -> dict[str, Any]:
    """Run all policies on the same scenarios and save the results."""

    scenarios = generate_scenarios()

    policy_results = {}

    for policy_name in POLICIES:
        result = evaluate_policy(policy_name, scenarios)

        result["metrics_by_noise_level"] = evaluate_by_noise(
            policy_name,
            scenarios,
        )

        # Keep the summary compact; detailed decisions are saved
        # separately for reproducibility and error analysis.
        policy_results[policy_name] = result

    summary = {
        policy_name: {
            key: value
            for key, value in result.items()
            if key not in {"details"}
        }
        for policy_name, result in policy_results.items()
    }

    output = {
        "benchmark_name": (
            "TripPilot Evidence-Gated Policy Baseline Comparison"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "scenario_count": len(scenarios),
        "policies": summary,
        "detailed_results": {
            policy_name: result["details"]
            for policy_name, result in policy_results.items()
        },
        "scenario_data": scenarios,
        "limitations": [
            "Results are from synthetic scenarios, not real-world trips.",
            "Synthetic source reliability is generated rather than learned "
            "from historical source accuracy.",
            "The benchmark uses simplified disruption claims and does "
            "not yet evaluate itinerary feasibility.",
            "The evidence-gated benchmark policy is a separate experiment "
            "and is not identical to assess_evidence in evidence.py.",
            "Thresholds require sensitivity analysis before conclusions "
            "about policy superiority can be made.",
        ],
    }

    output_path = (
        Path(__file__).resolve().parent.parent
        / "benchmark_results.json"
    )

    output_path.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print("\n=== TripPilot Baseline Benchmark ===\n")

    for policy_name, metrics in summary.items():
        print(f"Policy: {policy_name}")
        print(f"  Accuracy: {metrics['decision_accuracy']:.3f}")
        print(
            "  Unnecessary repair rate: "
            f"{metrics['unnecessary_repair_rate']:.3f}"
        )
        print(
            "  Missed disruption rate: "
            f"{metrics['missed_disruption_rate']:.3f}"
        )
        print(f"  Repair rate: {metrics['repair_rate']:.3f}")
        print()

    print(f"Saved results to: {output_path}")

    return output


if __name__ == "__main__":
    run_benchmark()