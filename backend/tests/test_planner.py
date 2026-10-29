import pytest
from app.planner import repair_itinerary_budget
from app.planner import minimal_change_replan


@pytest.fixture
def sample_itinerary():
    return [
        {
            "day": 1,
            "activities": [
                {
                    "title": "Outdoor sightseeing",
                    "category": "outdoor",
                    "estimated_cost": 1200,
                },
                {
                    "title": "Visit museum",
                    "category": "culture",
                    "estimated_cost": 200,
                },
                {
                    "title": "Local shopping",
                    "category": "shopping",
                    "estimated_cost": 300,
                },
            ],
            "estimated_daily_cost": 1700,
        }
    ]


def test_weather_repair_changes_only_affected_activity(sample_itinerary):
    original = [
        {
            **day,
            "activities": [activity.copy() for activity in day["activities"]],
        }
        for day in sample_itinerary
    ]

    evidence = {
        "disruption_type": "weather",
        "affected_day": 1,
        "affected_activity_index": 0,
    }

    updated, changes = minimal_change_replan(
        sample_itinerary, evidence, travelers=2
    )

    assert len(changes) == 1
    assert changes[0]["old_activity"] == "Outdoor sightseeing"
    assert updated[0]["activities"][0]["title"] == (
        "Indoor cultural activity (weather alternative)"
    )

    # Activities not affected by the disruption must remain unchanged.
    assert updated[0]["activities"][1:] == (
        original[0]["activities"][1:]
    )

    # The original itinerary must not be mutated.
    assert sample_itinerary == original


def test_repair_recalculates_daily_cost(sample_itinerary):
    evidence = {
        "disruption_type": "weather",
        "affected_day": 1,
        "affected_activity_index": 0,
    }

    updated, _ = minimal_change_replan(
        sample_itinerary, evidence, travelers=2
    )

    expected_cost = sum(
        activity["estimated_cost"]
        for activity in updated[0]["activities"]
    )

    assert updated[0]["estimated_daily_cost"] == expected_cost


def test_invalid_affected_day_is_rejected(sample_itinerary):
    evidence = {
        "disruption_type": "weather",
        "affected_day": 2,
        "affected_activity_index": 0,
    }

    with pytest.raises(ValueError, match="affected_day"):
        minimal_change_replan(sample_itinerary, evidence, travelers=2)


def test_invalid_activity_index_is_rejected(sample_itinerary):
    evidence = {
        "disruption_type": "weather",
        "affected_day": 1,
        "affected_activity_index": 5,
    }

    with pytest.raises(ValueError, match="activity index"):
        minimal_change_replan(sample_itinerary, evidence, travelers=2)

def test_budget_repair_preserves_itinerary_when_already_within_budget(
    sample_itinerary,
):
    updated, changes = repair_itinerary_budget(
        sample_itinerary,
        budget=2000,
    )

    assert updated == sample_itinerary
    assert changes == []


def test_budget_repair_reduces_cost_to_fit_budget(sample_itinerary):
    budget = 1000

    updated, changes = repair_itinerary_budget(
        sample_itinerary,
        budget=budget,
    )

    total = sum(
        activity["estimated_cost"]
        for day in updated
        for activity in day["activities"]
    )

    assert total <= budget
    assert len(changes) >= 1


def test_budget_repair_preserves_activity_details(sample_itinerary):
    original_title = sample_itinerary[0]["activities"][0]["title"]
    original_category = sample_itinerary[0]["activities"][0]["category"]

    updated, _ = repair_itinerary_budget(
        sample_itinerary,
        budget=1000,
    )

    activity = updated[0]["activities"][0]

    assert activity["title"] == original_title
    assert activity["category"] == original_category


def test_budget_repair_does_not_mutate_original(sample_itinerary):
    original = [
        {
            **day,
            "activities": [
                activity.copy()
                for activity in day["activities"]
            ],
        }
        for day in sample_itinerary
    ]

    repair_itinerary_budget(sample_itinerary, budget=1000)

    assert sample_itinerary == original


def test_budget_repair_rejects_negative_budget(sample_itinerary):
    with pytest.raises(ValueError, match="Budget cannot be negative"):
        repair_itinerary_budget(sample_itinerary, budget=-1)
def test_budget_repair_never_reduces_activity_below_minimum(
    sample_itinerary,
):
    updated, changes = repair_itinerary_budget(
        sample_itinerary,
        budget=1000,
        minimum_activity_cost=100,
    )

    costs = [
        activity["estimated_cost"]
        for day in updated
        for activity in day["activities"]
    ]

    assert all(cost >= 100 for cost in costs)
    assert sum(costs) <= 1000
    assert len(changes) > 0
# --------------------------------------------------
# REAL ITINERARY VALIDATION TESTS
# These tests use the actual validate_itinerary()
# function instead of a mocked validator.
# --------------------------------------------------

from copy import deepcopy

from app.planner import validate_itinerary


def make_validation_itinerary():
    """Create a valid itinerary for validation tests."""
    return [
        {
            "day": 1,
            "date": "2026-11-01",
            "destination": "Jaipur",
            "activities": [
                {
                    "time": "09:00",
                    "duration_minutes": 120,
                    "title": "Visit museum",
                    "estimated_cost": 500,
                    "category": "indoor",
                },
                {
                    "time": "12:00",
                    "duration_minutes": 90,
                    "title": "Explore local market",
                    "estimated_cost": 300,
                    "category": "outdoor",
                },
                {
                    "time": "15:00",
                    "duration_minutes": 60,
                    "title": "Visit heritage site",
                    "estimated_cost": 200,
                    "category": "indoor",
                },
            ],
            "estimated_daily_cost": 1000,
        }
    ]


def test_real_validation_accepts_valid_itinerary():
    itinerary = make_validation_itinerary()

    result = validate_itinerary(itinerary, budget=1500)

    assert result["is_valid"] is True
    assert result["errors"] == []
    assert result["estimated_total_cost"] == 1000
    assert result["budget"] == 1500
    assert result["remaining_budget"] == 500
    assert len(result["warnings"]) >= 1


def test_real_validation_rejects_itinerary_over_budget():
    itinerary = make_validation_itinerary()

    result = validate_itinerary(itinerary, budget=900)

    assert result["is_valid"] is False
    assert any(
        "exceeds budget" in error
        for error in result["errors"]
    )
    assert result["estimated_total_cost"] == 1000
    assert result["remaining_budget"] == -100


def test_real_validation_detects_overlapping_activities():
    itinerary = make_validation_itinerary()

    # The first activity ends at 11:00.
    # The second starts at 10:30, creating an overlap.
    itinerary[0]["activities"][1]["time"] = "10:30"

    result = validate_itinerary(itinerary, budget=1500)

    assert result["is_valid"] is False
    assert any(
        "overlapping activities" in error
        for error in result["errors"]
    )


def test_real_validation_rejects_invalid_time():
    itinerary = make_validation_itinerary()

    itinerary[0]["activities"][0]["time"] = "25:70"

    result = validate_itinerary(itinerary, budget=1500)

    assert result["is_valid"] is False
    assert any(
        "invalid time" in error
        for error in result["errors"]
    )


def test_real_validation_rejects_zero_duration():
    itinerary = make_validation_itinerary()

    itinerary[0]["activities"][0]["duration_minutes"] = 0

    result = validate_itinerary(itinerary, budget=1500)

    assert result["is_valid"] is False
    assert any(
        "invalid duration" in error
        for error in result["errors"]
    )


def test_real_validation_recalculates_daily_cost():
    itinerary = make_validation_itinerary()

    # Deliberately supply an incorrect daily total.
    itinerary[0]["estimated_daily_cost"] = 9999

    result = validate_itinerary(itinerary, budget=1500)

    assert itinerary[0]["estimated_daily_cost"] == 1000
    assert result["estimated_total_cost"] == 1000
    assert result["remaining_budget"] == 500


def test_real_validation_does_not_modify_activity_details():
    itinerary = make_validation_itinerary()
    original = deepcopy(itinerary)

    validate_itinerary(itinerary, budget=1500)

    # Validation recalculates estimated_daily_cost, so compare
    # activity details rather than the entire itinerary.
    assert (
        itinerary[0]["activities"]
        == original[0]["activities"]
    )


def test_real_validation_accepts_activity_ending_at_next_start():
    itinerary = make_validation_itinerary()

    # First activity: 09:00 to 11:00.
    # Second activity begins exactly at 11:00.
    itinerary[0]["activities"][1]["time"] = "11:00"

    result = validate_itinerary(itinerary, budget=1500)

    assert not any(
        "overlapping activities" in error
        for error in result["errors"]
    )
