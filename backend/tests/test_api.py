from copy import deepcopy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def api():
    itinerary = [
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

    state = {
        "record": {
            "request": {"travelers": 2},
            "current_itinerary": deepcopy(itinerary),
            "budget": 5000.0,
            "revision": 0,
        },
        "revisions": [],
        "evidence": [],
    }

    # Keep these tests isolated from the real SQLite database.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(main.database, "init_db", lambda: None)

    def get_trip(trip_id):
        if trip_id == "trip-test":
            return state["record"]
        return None

    def update_trip(trip_id, updated_itinerary, budget, revision):
        state["record"]["current_itinerary"] = deepcopy(
            updated_itinerary
        )
        state["record"]["budget"] = budget
        state["record"]["revision"] = revision

    monkeypatch.setattr(main.database, "get_trip", get_trip)
    monkeypatch.setattr(main.database, "update_trip", update_trip)

    monkeypatch.setattr(
        main.database,
        "add_revision",
        lambda *args: state["revisions"].append(args),
    )

    monkeypatch.setattr(
        main.database,
        "add_evidence",
        lambda *args: state["evidence"].append(args),
    )

    # Mock successful itinerary validation for API tests.
    # The API expects the key "is_valid".
    monkeypatch.setattr(
        main,
        "validate_itinerary",
        lambda itinerary, budget: {"is_valid": True},
    )

    try:
        with TestClient(main.app) as client:
            yield client, state
    finally:
        monkeypatch.undo()


def evidence_payload(**overrides):
    evidence = {
        "disruption_type": "weather",
        "affected_day": 1,
        "affected_activity_index": 0,
        "source": "Test weather source",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "confidence": 1.0,
        "source_reliability": 1.0,
        "claim": "Outdoor attraction is closed due to severe weather.",
        "corroborating_sources": ["Source B", "Source C"],
        "conflicting_claims": [],
    }

    evidence.update(overrides)

    return {
        "trip_id": "trip-test",
        "evidence": evidence,
    }


# --------------------------------------------------
# EVIDENCE-BASED REPLANNING TESTS
# --------------------------------------------------

def test_strong_evidence_repairs_itinerary(api):
    client, state = api

    response = client.post(
        "/api/trips/replan",
        json=evidence_payload(),
    )

    assert response.status_code == 200

    result = response.json()

    assert result["decision"] == "repair"
    assert result["revision"] == 1
    assert len(result["changes"]) == 1

    assert (
        result["current_itinerary"][0]["activities"][0]["title"]
        == "Indoor cultural activity (weather alternative)"
    )

    assert len(state["revisions"]) == 1
    assert len(state["evidence"]) == 1


def test_conflicting_evidence_does_not_change_itinerary(api):
    client, state = api

    original = deepcopy(state["record"]["current_itinerary"])

    response = client.post(
        "/api/trips/replan",
        json=evidence_payload(
            conflicting_claims=[
                "Another source reports normal conditions."
            ]
        ),
    )

    assert response.status_code == 200

    result = response.json()

    assert result["decision"] == "warn"
    assert result["changes"] == []
    assert result["revision"] == 0
    assert result["current_itinerary"] == original
    assert state["revisions"] == []


def test_weak_evidence_does_not_change_itinerary(api):
    client, state = api

    original = deepcopy(state["record"]["current_itinerary"])

    response = client.post(
        "/api/trips/replan",
        json=evidence_payload(
            confidence=0.0,
            source_reliability=0.0,
            corroborating_sources=[],
        ),
    )

    assert response.status_code == 200

    result = response.json()

    assert result["decision"] == "retain"
    assert result["changes"] == []
    assert result["revision"] == 0
    assert result["current_itinerary"] == original
    assert state["revisions"] == []


def test_unknown_trip_returns_404(api):
    client, _ = api

    payload = evidence_payload()
    payload["trip_id"] = "unknown-trip"

    response = client.post(
        "/api/trips/replan",
        json=payload,
    )

    assert response.status_code == 404


# --------------------------------------------------
# BUDGET UPDATE API TESTS
# --------------------------------------------------

def test_budget_update_succeeds_and_increments_revision(api):
    client, state = api

    response = client.post(
        "/api/trips/budget",
        json={
            "trip_id": "trip-test",
            "new_budget": 1000,
        },
    )

    assert response.status_code == 200

    result = response.json()

    assert result["success"] is True
    assert result["budget"] == 1000
    assert result["revision"] == 1
    assert result["validation"]["is_valid"] is True

    # Confirm the mocked database received the update.
    assert state["record"]["budget"] == 1000
    assert state["record"]["revision"] == 1
    assert len(state["revisions"]) == 1


def test_budget_update_unknown_trip_returns_404(api):
    client, state = api

    original_itinerary = deepcopy(
        state["record"]["current_itinerary"]
    )

    response = client.post(
        "/api/trips/budget",
        json={
            "trip_id": "unknown-trip",
            "new_budget": 1000,
        },
    )

    assert response.status_code == 404

    # The existing trip must remain unchanged.
    assert (
        state["record"]["current_itinerary"]
        == original_itinerary
    )
    assert state["record"]["budget"] == 5000.0
    assert state["record"]["revision"] == 0
    assert state["revisions"] == []


def test_impossible_budget_does_not_modify_existing_trip(api):
    client, state = api

    original_itinerary = deepcopy(
        state["record"]["current_itinerary"]
    )

    response = client.post(
        "/api/trips/budget",
        json={
            "trip_id": "trip-test",
            "new_budget": 1,
        },
    )

    assert response.status_code == 422

    # A failed repair must not modify the saved trip.
    assert (
        state["record"]["current_itinerary"]
        == original_itinerary
    )
    assert state["record"]["budget"] == 5000.0
    assert state["record"]["revision"] == 0
    assert state["revisions"] == []