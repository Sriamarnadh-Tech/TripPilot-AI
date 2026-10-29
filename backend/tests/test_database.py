import json

import pytest

from app import database


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Use an isolated temporary SQLite database for every test.
    The real adaptivetrip.db file remains untouched.
    """
    temporary_db = tmp_path / "test_adaptivetrip.db"

    monkeypatch.setattr(database, "DB_PATH", temporary_db)

    database.init_db()

    return temporary_db


@pytest.fixture
def sample_trip():
    return {
        "id": "trip-test-001",
        "created_at": "2026-10-29T10:00:00+00:00",
        "request": {
            "destination": "Jaipur",
            "travelers": 2,
            "days": 2,
            "travel_style": "Balanced",
        },
        "itinerary": [
            {
                "day": 1,
                "date": "2026-11-01",
                "destination": "Jaipur",
                "activities": [
                    {
                        "time": "09:00",
                        "title": "Visit City Palace",
                        "estimated_cost": 500,
                    },
                    {
                        "time": "12:00",
                        "title": "Lunch",
                        "estimated_cost": 300,
                    },
                ],
                "estimated_daily_cost": 800,
            }
        ],
        "budget": 5000.0,
    }


def create_sample_trip(sample_trip):
    database.create_trip(
        tid=sample_trip["id"],
        created=sample_trip["created_at"],
        request=sample_trip["request"],
        itinerary=sample_trip["itinerary"],
        budget=sample_trip["budget"],
    )


def test_database_initializes_tables(test_db):
    """Verify that all required database tables are created."""
    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

    assert {"trips", "evidence", "revisions"}.issubset(tables)


def test_create_and_retrieve_trip(test_db, sample_trip):
    """Verify that a trip is saved and retrieved correctly."""
    create_sample_trip(sample_trip)

    trip = database.get_trip(sample_trip["id"])

    assert trip is not None
    assert trip["id"] == sample_trip["id"]
    assert trip["created_at"] == sample_trip["created_at"]
    assert trip["request"] == sample_trip["request"]
    assert trip["current_itinerary"] == sample_trip["itinerary"]
    assert trip["original_itinerary"] == sample_trip["itinerary"]
    assert trip["budget"] == sample_trip["budget"]
    assert trip["revision"] == 0


def test_get_trip_returns_none_for_unknown_id(test_db):
    """An unknown trip ID should return None."""
    assert database.get_trip("nonexistent-trip") is None


def test_update_trip_persists_itinerary_budget_and_revision(
    test_db, sample_trip
):
    """Verify that itinerary, budget, and revision changes persist."""
    create_sample_trip(sample_trip)

    updated_itinerary = [
        {
            "day": 1,
            "date": "2026-11-01",
            "destination": "Jaipur",
            "activities": [
                {
                    "time": "10:00",
                    "title": "Visit Albert Hall Museum",
                    "estimated_cost": 400,
                }
            ],
            "estimated_daily_cost": 400,
        }
    ]

    database.update_trip(
        tid=sample_trip["id"],
        itinerary=updated_itinerary,
        budget=3500.0,
        revision=1,
    )

    trip = database.get_trip(sample_trip["id"])

    assert trip["current_itinerary"] == updated_itinerary
    assert trip["budget"] == 3500.0
    assert trip["revision"] == 1

    # Updating the current itinerary must not overwrite the original.
    assert trip["original_itinerary"] == sample_trip["itinerary"]


def test_add_evidence_persists_json_data(test_db, sample_trip):
    """Verify that evidence and its assessment are stored correctly."""
    create_sample_trip(sample_trip)

    evidence = {
        "type": "weather",
        "description": "Heavy rain expected",
        "confidence": 0.95,
        "source": "Weather provider",
    }

    assessment = {
        "decision": "repair",
        "confidence": 0.92,
        "reason": "Strong evidence supports changing outdoor activities.",
    }

    evidence_id = database.add_evidence(
        tid=sample_trip["id"],
        received="2026-10-29T10:30:00+00:00",
        evidence=evidence,
        assessment=assessment,
    )

    assert isinstance(evidence_id, int)
    assert evidence_id > 0

    history = database.history(sample_trip["id"])

    assert len(history["evidence"]) == 1

    stored_evidence = history["evidence"][0]

    assert stored_evidence["id"] == evidence_id
    assert stored_evidence["trip_id"] == sample_trip["id"]
    assert stored_evidence["evidence"] == evidence
    assert stored_evidence["assessment"] == assessment


def test_add_revision_persists_revision_details(test_db, sample_trip):
    """Verify that revision details and JSON fields are stored."""
    create_sample_trip(sample_trip)

    validation = {
        "is_valid": True,
        "errors": [],
        "estimated_total_cost": 800.0,
        "budget": 5000.0,
    }

    database.add_revision(
        tid=sample_trip["id"],
        rev=1,
        created="2026-10-29T11:00:00+00:00",
        decision="repair",
        reason="Strong weather evidence",
        itinerary=sample_trip["itinerary"],
        validation=validation,
    )

    history = database.history(sample_trip["id"])

    assert len(history["revisions"]) == 1

    revision = history["revisions"][0]

    assert revision["trip_id"] == sample_trip["id"]
    assert revision["revision"] == 1
    assert revision["decision"] == "repair"
    assert revision["reason"] == "Strong weather evidence"
    assert revision["itinerary"] == sample_trip["itinerary"]
    assert revision["validation"] == validation


def test_history_orders_revisions_by_revision_number(
    test_db, sample_trip
):
    """Revision history should be returned in ascending revision order."""
    create_sample_trip(sample_trip)

    for revision_number in [2, 1, 3]:
        database.add_revision(
            tid=sample_trip["id"],
            rev=revision_number,
            created=f"2026-10-29T{revision_number:02d}:00:00+00:00",
            decision="repair",
            reason=f"Revision {revision_number}",
            itinerary=sample_trip["itinerary"],
            validation={"is_valid": True},
        )

    history = database.history(sample_trip["id"])

    revision_numbers = [
        revision["revision"]
        for revision in history["revisions"]
    ]

    assert revision_numbers == [1, 2, 3]


def test_history_isolates_records_by_trip(test_db, sample_trip):
    """Evidence and revisions for one trip must not appear in another."""
    create_sample_trip(sample_trip)

    second_trip_id = "trip-test-002"

    database.create_trip(
        tid=second_trip_id,
        created=sample_trip["created_at"],
        request={"destination": "Agra", "travelers": 1},
        itinerary=[],
        budget=2000.0,
    )

    database.add_evidence(
        tid=sample_trip["id"],
        received="2026-10-29T12:00:00+00:00",
        evidence={"type": "weather"},
        assessment={"decision": "repair"},
    )

    database.add_revision(
        tid=second_trip_id,
        rev=1,
        created="2026-10-29T12:30:00+00:00",
        decision="initial",
        reason="Initial itinerary",
        itinerary=[],
        validation={"is_valid": True},
    )

    first_history = database.history(sample_trip["id"])
    second_history = database.history(second_trip_id)

    assert len(first_history["evidence"]) == 1
    assert len(first_history["revisions"]) == 0

    assert len(second_history["evidence"]) == 0
    assert len(second_history["revisions"]) == 1


def test_duplicate_trip_id_is_rejected(test_db, sample_trip):
    """The trips primary key should prevent duplicate trip IDs."""
    create_sample_trip(sample_trip)

    with pytest.raises(Exception) as exc_info:
        create_sample_trip(sample_trip)

    assert isinstance(exc_info.value, Exception)