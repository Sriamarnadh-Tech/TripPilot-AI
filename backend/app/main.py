from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import database
from .schemas import (
    TripRequest,
    ReplanRequest,
    BudgetUpdateRequest,
)
from .planner import (
    generate_itinerary,
    validate_itinerary,
    minimal_change_replan,
    repair_itinerary_budget,
)
from .evidence import assess_evidence
from .discovery import discover_places


app = FastAPI(
    title="TripPilot API",
    description=(
        "Evidence-aware adaptive travel planning "
        "with live place discovery."
    ),
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    database.init_db()


@app.get("/")
def root():
    return {
        "project": "AdaptiveTrip",
        "status": "running",
        "version": "1.1.0",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# ---------------------------------------------------------
# LIVE PLACE DISCOVERY
# ---------------------------------------------------------

@app.get("/api/discover/places")
def search_places(
    destination: str,
    category: str = "both",
    radius_m: int = 7000,
    limit: int = 30,
):
    """
    Discover mapped attractions and restaurants.

    Example:
    /api/discover/places?destination=Jaipur&category=both
    """

    return discover_places(
        destination=destination,
        category=category,
        radius_m=radius_m,
        limit=limit,
    )


# ---------------------------------------------------------
# INITIAL TRIP PLANNING
# ---------------------------------------------------------

@app.post("/api/trips/plan")
def create_plan(trip: TripRequest):
    request_data = trip.model_dump(mode="json")
    itinerary = generate_itinerary(trip.model_dump())

    validation = validate_itinerary(
        itinerary,
        trip.budget,
    )

    trip_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    database.create_trip(
        trip_id,
        now,
        request_data,
        itinerary,
        trip.budget,
    )

    database.add_revision(
        trip_id,
        0,
        now,
        "initial_plan",
        "Initial itinerary generated.",
        itinerary,
        validation,
    )

    return {
        "success": True,
        "trip_id": trip_id,
        "message": "Initial itinerary generated",
        "trip": {
            "destination": trip.destination,
            "start_date": trip.startDate.isoformat(),
            "end_date": trip.endDate.isoformat(),
            "trip_days": len(itinerary),
            "budget": trip.budget,
            "currency": "INR",
            "travelers": trip.travelers,
            "interests": trip.interests,
            "travel_style": trip.travelStyle,
        },
        "itinerary": itinerary,
        "validation": validation,
        "planning_notes": [
            "The initial itinerary still uses illustrative activities and costs.",
            "Live place discovery is available through /api/discover/places.",
            "The live place results are not yet automatically inserted into the itinerary.",
        ],
    }


# ---------------------------------------------------------
# RETRIEVE A TRIP
# ---------------------------------------------------------

@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: str):
    record = database.get_trip(trip_id)

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    return record


# ---------------------------------------------------------
# EVIDENCE-BASED REPLANNING
# ---------------------------------------------------------

@app.post("/api/trips/replan")
def replan(request: ReplanRequest):
    record = database.get_trip(request.trip_id)

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Trip not found. Create a plan first.",
        )

    evidence = request.evidence.model_dump()
    now = datetime.now(timezone.utc)

    try:
        assessment = assess_evidence(
            evidence,
            now,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid evidence timestamp: {exc}",
        ) from exc

    itinerary = record["current_itinerary"]
    budget = float(record["budget"])
    decision = assessment["decision"]
    changes = []
    revision = int(record["revision"])

    if decision == "repair":
        try:
            itinerary, changes = minimal_change_replan(
                itinerary,
                evidence,
                record["request"]["travelers"],
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        revision += 1

        database.update_trip(
            request.trip_id,
            itinerary,
            budget,
            revision,
        )

        validation = validate_itinerary(
            itinerary,
            budget,
        )

        database.add_revision(
            request.trip_id,
            revision,
            now.isoformat(),
            decision,
            assessment["reason"],
            itinerary,
            validation,
        )

    else:
        validation = validate_itinerary(
            itinerary,
            budget,
        )

    database.add_evidence(
        request.trip_id,
        now.isoformat(),
        evidence,
        assessment,
    )

    return {
        "success": True,
        "trip_id": request.trip_id,
        "evidence_assessment": assessment,
        "decision": decision,
        "reason": assessment["reason"],
        "changes": changes,
        "revision": revision,
        "current_itinerary": itinerary,
        "validation": validation,
        "limitations": [
            "Evidence source is user-supplied and not authenticated.",
            "Alternative activities and costs remain illustrative.",
            "Live place discovery is available separately.",
        ],
    }


# ---------------------------------------------------------
# BUDGET UPDATE
# ---------------------------------------------------------
@app.post("/api/trips/budget")
def budget_update(request: BudgetUpdateRequest):
    record = database.get_trip(request.trip_id)

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    itinerary = record["current_itinerary"]
    new_budget = float(request.new_budget)

    try:
        updated_itinerary, changes = repair_itinerary_budget(
            itinerary=itinerary,
            budget=new_budget,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    validation = validate_itinerary(
        updated_itinerary,
        new_budget,
    )

    if not validation["is_valid"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The revised itinerary failed validation.",
                "validation": validation,
            },
        )

    revision = int(record["revision"]) + 1
    now = datetime.now(timezone.utc).isoformat()

    database.update_trip(
        request.trip_id,
        updated_itinerary,
        new_budget,
        revision,
    )

    database.add_revision(
        request.trip_id,
        revision,
        now,
        "budget_replan",
        (
            "Budget updated. "
            f"{len(changes)} activity cost estimate(s) adjusted."
            if changes
            else "Budget updated. Existing itinerary retained."
        ),
        updated_itinerary,
        validation,
    )

    return {
        "success": True,
        "trip_id": request.trip_id,
        "revision": revision,
        "budget": new_budget,
        "currency": "INR",
        "changes": changes,
        "itinerary": updated_itinerary,
        "validation": validation,
        "limitations": [
            "Adjusted activity costs are estimates, not verified prices.",
            "Activity availability and live prices are not verified.",
            "The budget repair preserves activities but may reduce "
            "their estimated costs without identifying cheaper alternatives.",
        ],
    }
# ---------------------------------------------------------
# TRIP HISTORY
# ---------------------------------------------------------

@app.get("/api/trips/{trip_id}/history")
def get_history(trip_id: str):
    if not database.get_trip(trip_id):
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    return database.history(trip_id)