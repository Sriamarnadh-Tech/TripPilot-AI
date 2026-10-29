import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import database, main


@pytest.fixture
def integration_client(tmp_path, monkeypatch):
    """
    Run API integration tests against a temporary SQLite database.
    Use real database functions instead of mocking persistence.
    """
    test_db_path = tmp_path / "integration_test.db"

    monkeypatch.setattr(database, "DB_PATH", test_db_path)

    with TestClient(main.app) as client:
        yield client

    # Confirm that the test database was isolated.
    assert test_db_path.exists()


def valid_trip_payload():
    start_date = datetime.now().date() + timedelta(days=7)
    end_date = start_date + timedelta(days=1)

    return {
        "destination": "Jaipur",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "budget": 10000,
        "travelers": 2,
        "interests": ["culture", "food"],
        "travelStyle": "Balanced",
    }


def create_trip(client, budget=10000):
    payload = valid_trip_payload()
    payload["budget"] = budget

    response = client.post("/api/trips/plan", json=payload)

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["success"] is True
    assert data["trip_id"]

    return data


def valid_evidence_payload(trip_id, **overrides):
    """
    Build a valid evidence payload.

    Supports both direct overrides and a nested evidence dictionary.
    """
    now = datetime.now(timezone.utc)

    evidence = {
        "disruption_type": "weather",
        "affected_day": 1,
        "affected_activity_index": 0,
        "observed_at": now.isoformat(),
        "claim": "Severe weather expected at the destination",
        "confidence": 0.95,
        "source_reliability": 0.95,
        "source": "Official weather authority",
        "corroborating_sources": [
            "weather_authority",
            "official_alert",
        ],
        "conflicting_claims": [],
    }

    # Support calls that pass evidence={...}.
    evidence_overrides = overrides.pop("evidence", {})
    evidence.update(evidence_overrides)

    # Support calls that pass fields directly.
    evidence.update(overrides)

    return {
        "trip_id": trip_id,
        "evidence": evidence,
    }


def test_create_trip_persists_trip_and_initial_revision(
    integration_client,
):
    client = integration_client

    created = create_trip(client)
    trip_id = created["trip_id"]

    response = client.get(f"/api/trips/{trip_id}")

    assert response.status_code == 200

    saved_trip = response.json()

    assert saved_trip["id"] == trip_id
    assert saved_trip["budget"] == 10000
    assert saved_trip["revision"] == 0
    assert saved_trip["current_itinerary"] == created["itinerary"]
    assert saved_trip["original_itinerary"] == created["itinerary"]

    history_response = client.get(
        f"/api/trips/{trip_id}/history"
    )

    assert history_response.status_code == 200

    history = history_response.json()

    assert len(history["revisions"]) == 1
    assert history["revisions"][0]["revision"] == 0
    assert history["revisions"][0]["decision"] == "initial_plan"


def test_trip_creation_survives_database_reconnection(
    integration_client,
):
    """
    Verify that a trip can be retrieved through a fresh SQLite connection.
    """
    client = integration_client

    created = create_trip(client)
    trip_id = created["trip_id"]

    # database.get_trip opens a new SQLite connection.
    saved_trip = database.get_trip(trip_id)

    assert saved_trip is not None
    assert saved_trip["id"] == trip_id
    assert saved_trip["revision"] == 0


def test_strong_evidence_persists_repair_and_history(
    integration_client,
):
    client = integration_client

    created = create_trip(client)
    trip_id = created["trip_id"]

    before = client.get(f"/api/trips/{trip_id}").json()

    request_payload = valid_evidence_payload(trip_id)

    response = client.post(
        "/api/trips/replan",
        json=request_payload,
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["success"] is True
    assert result["trip_id"] == trip_id

    # Strong evidence is expected to trigger a repair.
    assert result["decision"] == "repair", result
    assert result["revision"] == 1
    assert result["changes"]

    after = client.get(f"/api/trips/{trip_id}").json()

    assert after["revision"] == 1
    assert after["current_itinerary"] == result["current_itinerary"]

    history = client.get(
        f"/api/trips/{trip_id}/history"
    ).json()

    assert len(history["evidence"]) == 1
    assert len(history["revisions"]) == 2
    assert history["revisions"][-1]["revision"] == 1


def test_sequential_disruptions_persist_both_repairs(
    integration_client,
):
    """
    Verify that two successive disruptions can be processed and persisted.

    The second repair must preserve the first repair while updating
    the activity affected by the second disruption.
    """
    client = integration_client

    # Create the initial trip.
    created = create_trip(client)
    trip_id = created["trip_id"]

    initial = client.get(f"/api/trips/{trip_id}").json()

    assert initial["revision"] == 0

    # First disruption: activity index 0.
    first_payload = valid_evidence_payload(
        trip_id,
        affected_day=1,
        affected_activity_index=0,
        claim="Severe weather affects the first planned activity",
        source="Weather authority",
        confidence=0.95,
        source_reliability=0.95,
        corroborating_sources=[
            "weather_authority",
            "official_alert",
        ],
    )

    first_response = client.post(
        "/api/trips/replan",
        json=first_payload,
    )

    assert first_response.status_code == 200, first_response.text

    first_result = first_response.json()

    assert first_result["success"] is True
    assert first_result["decision"] == "repair", first_result
    assert first_result["revision"] == 1

    after_first = client.get(
        f"/api/trips/{trip_id}"
    ).json()

    assert after_first["revision"] == 1
    assert (
        after_first["current_itinerary"]
        == first_result["current_itinerary"]
    )

    # Capture the first repaired activity so we can verify that the
    # second repair does not overwrite or undo it.
    first_repaired_activity = (
        after_first["current_itinerary"][0]["activities"][0].copy()
    )

    # Second disruption: activity index 1.
    # The first repair has already been persisted.
    second_payload = valid_evidence_payload(
        trip_id,
        disruption_type="transport",
        affected_day=1,
        affected_activity_index=1,
        claim="A transport disruption affects another planned activity",
        source="Transport authority",
        confidence=0.95,
        source_reliability=0.95,
        corroborating_sources=[
            "transport_authority",
            "official_alert",
        ],
    )

    second_response = client.post(
        "/api/trips/replan",
        json=second_payload,
    )

    assert second_response.status_code == 200, second_response.text

    second_result = second_response.json()

    assert second_result["success"] is True
    assert second_result["decision"] == "repair", second_result
    assert second_result["revision"] == 2

    # Verify that the second repair is saved.
    after_second = client.get(
        f"/api/trips/{trip_id}"
    ).json()

    assert after_second["revision"] == 2
    assert (
        after_second["current_itinerary"]
        == second_result["current_itinerary"]
    )

    # NEW ASSERTION 1:
    # The second repair must preserve the first repair.
    final_first_activity = (
        after_second["current_itinerary"][0]["activities"][0]
    )

    assert final_first_activity == first_repaired_activity

    # NEW ASSERTION 2:
    # The second disruption should update the targeted activity.
    final_second_activity = (
        after_second["current_itinerary"][0]["activities"][1]
    )

    assert final_second_activity["title"] == (
        "Nearby activity to reduce transport dependency"
    )

    # Verify that both evidence submissions and repairs are recorded.
    history_response = client.get(
        f"/api/trips/{trip_id}/history"
    )

    assert history_response.status_code == 200

    history = history_response.json()

    assert len(history["evidence"]) == 2
    assert len(history["revisions"]) == 3

    assert [
        revision["revision"]
        for revision in history["revisions"]
    ] == [0, 1, 2]


def test_weak_evidence_does_not_change_saved_itinerary(
    integration_client,
):
    client = integration_client

    created = create_trip(client)
    trip_id = created["trip_id"]

    before = client.get(f"/api/trips/{trip_id}").json()

    request_payload = valid_evidence_payload(
        trip_id,
        evidence={
            "disruption_type": "weather",
            "affected_day": 1,
            "affected_activity_index": 0,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "claim": "Unverified weather rumor",
            "confidence": 0.1,
            "source_reliability": 0.1,
            "source": "Unverified source",
            "corroborating_sources": [],
            "conflicting_claims": [],
        },
    )

    response = client.post(
        "/api/trips/replan",
        json=request_payload,
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["decision"] == "retain"

    after = client.get(f"/api/trips/{trip_id}").json()

    assert after["revision"] == before["revision"]
    assert after["current_itinerary"] == before["current_itinerary"]

    history = client.get(
        f"/api/trips/{trip_id}/history"
    ).json()

    assert len(history["evidence"]) == 1
    assert len(history["revisions"]) == 1


def test_budget_update_persists_in_sqlite(integration_client):
    client = integration_client

    created = create_trip(client, budget=10000)
    trip_id = created["trip_id"]

    response = client.post(
        "/api/trips/budget",
        json={
            "trip_id": trip_id,
            "new_budget": 8000,
        },
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["success"] is True
    assert result["budget"] == 8000
    assert result["revision"] == 1
    assert result["validation"]["is_valid"] is True

    saved_trip = client.get(f"/api/trips/{trip_id}").json()

    assert saved_trip["budget"] == 8000
    assert saved_trip["revision"] == 1
    assert saved_trip["current_itinerary"] == result["itinerary"]

    history = client.get(
        f"/api/trips/{trip_id}/history"
    ).json()

    assert len(history["revisions"]) == 2
    assert history["revisions"][-1]["decision"] == "budget_replan"


def test_unknown_trip_returns_404_for_retrieval_and_history(
    integration_client,
):
    client = integration_client

    assert client.get(
        "/api/trips/does-not-exist"
    ).status_code == 404

    assert client.get(
        "/api/trips/does-not-exist/history"
    ).status_code == 404


def test_unknown_trip_returns_404_for_budget_update(
    integration_client,
):
    client = integration_client

    response = client.post(
        "/api/trips/budget",
        json={
            "trip_id": "does-not-exist",
            "new_budget": 5000,
        },
    )

    assert response.status_code == 404


def test_impossible_budget_does_not_modify_persisted_trip(
    integration_client,
):
    client = integration_client

    created = create_trip(client, budget=10000)
    trip_id = created["trip_id"]

    before = client.get(f"/api/trips/{trip_id}").json()

    before_history = client.get(
        f"/api/trips/{trip_id}/history"
    ).json()

    response = client.post(
        "/api/trips/budget",
        json={
            "trip_id": trip_id,
            "new_budget": 1,
        },
    )

    assert response.status_code == 422

    after = client.get(f"/api/trips/{trip_id}").json()

    after_history = client.get(
        f"/api/trips/{trip_id}/history"
    ).json()

    assert after["budget"] == before["budget"]
    assert after["revision"] == before["revision"]
    assert after["current_itinerary"] == before["current_itinerary"]

    assert len(after_history["revisions"]) == len(
        before_history["revisions"]
    )