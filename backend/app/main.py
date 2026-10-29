from datetime import date, datetime, timezone
import requests
from .discovery import discover_places
from uuid import uuid4
import httpx
from contextlib import asynccontextmanager
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(
    title="AdaptiveTrip",
    version="1.1.0",
    lifespan=lifespan,
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
@app.get("/api/weather")
async def get_weather(destination: str, forecast_days: int = 3):
    """
    Fetch current weather and a daily forecast for an Indian destination.
    Uses Open-Meteo APIs; no API key required.
    """

    destination = destination.strip()

    if not destination:
        raise HTTPException(
            status_code=400,
            detail="Destination cannot be empty.",
        )

    if not 1 <= forecast_days <= 7:
        raise HTTPException(
            status_code=400,
            detail="forecast_days must be between 1 and 7.",
        )

    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url = "https://api.open-meteo.com/v1/forecast"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: Resolve the destination to coordinates.
            location_response = await client.get(
                geocoding_url,
                params={
                    "name": destination,
                    "count": 10,
                    "language": "en",
                    "format": "json",
                    "countryCode": "IN",
                },
            )
            location_response.raise_for_status()
            location_data = location_response.json()

            locations = location_data.get("results", [])

            if not locations:
                raise HTTPException(
                    status_code=404,
                    detail=f"No matching Indian location found for '{destination}'.",
                )

            # Prefer an exact city-name match where possible.
            location = next(
                (
                    item
                    for item in locations
                    if item.get("name", "").casefold()
                    == destination.casefold()
                ),
                locations[0],
            )

            latitude = location["latitude"]
            longitude = location["longitude"]

            # Step 2: Retrieve current conditions and daily forecasts.
            weather_response = await client.get(
                forecast_url,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,"
                        "relative_humidity_2m,"
                        "apparent_temperature,"
                        "precipitation,"
                        "weather_code,"
                        "wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,"
                        "temperature_2m_max,"
                        "temperature_2m_min,"
                        "precipitation_probability_max,"
                        "precipitation_sum,"
                        "wind_speed_10m_max"
                    ),
                    "forecast_days": forecast_days,
                    "timezone": "auto",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                },
            )
            weather_response.raise_for_status()
            weather_data = weather_response.json()

    except HTTPException:
        raise

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Weather service timed out. Please try again later.",
        )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve weather data from Open-Meteo.",
        )

    except (KeyError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Weather service returned an unexpected response.",
        )

    return {
        "destination": {
            "name": location.get("name"),
            "state": location.get("admin1"),
            "country": location.get("country"),
            "latitude": latitude,
            "longitude": longitude,
            "timezone": weather_data.get("timezone"),
        },
        "current_weather": weather_data.get("current", {}),
        "daily_forecast": weather_data.get("daily", {}),
        "units": {
            "temperature": "°C",
            "wind_speed": "km/h",
            "precipitation": "mm",
            "precipitation_probability": "%",
        },
        "source": "Open-Meteo",
        "source_url": "https://open-meteo.com/",
    }

@app.get("/api/route")
async def get_route(
    origin: str,
    destination: str,
):
    """
    Find a driving route between two Indian destinations.
    Uses Open-Meteo Geocoding and the public OSRM routing service.
    No API key required.
    """

    origin = origin.strip()
    destination = destination.strip()

    if not origin or not destination:
        raise HTTPException(
            status_code=400,
            detail="Origin and destination cannot be empty.",
        )

    if origin.casefold() == destination.casefold():
        raise HTTPException(
            status_code=400,
            detail="Origin and destination must be different.",
        )

    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
    osrm_url = "https://router.project-osrm.org/route/v1/driving"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:

            # Resolve both place names to coordinates.
            resolved_locations = []

            for place_name in (origin, destination):
                geo_response = await client.get(
                    geocoding_url,
                    params={
                        "name": place_name,
                        "count": 10,
                        "language": "en",
                        "format": "json",
                        "countryCode": "IN",
                    },
                )
                geo_response.raise_for_status()

                geo_data = geo_response.json()
                results = geo_data.get("results", [])

                if not results:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Location not found in India: {place_name}",
                    )

                # Prefer an exact name match.
                match = next(
                    (
                        item for item in results
                        if item.get("name", "").casefold()
                        == place_name.casefold()
                    ),
                    results[0],
                )

                resolved_locations.append(match)

            start, end = resolved_locations

            # OSRM expects longitude,latitude coordinates.
            coordinates = (
                f"{start['longitude']},{start['latitude']};"
                f"{end['longitude']},{end['latitude']}"
            )

            route_response = await client.get(
                f"{osrm_url}/{coordinates}",
                params={
                    "overview": "false",
                    "steps": "false",
                },
            )
            route_response.raise_for_status()

            route_data = route_response.json()

    except HTTPException:
        raise

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="The routing service timed out. Please try again.",
        )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve route information.",
        )

    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=502,
            detail="The location or routing service returned invalid data.",
        )

    if route_data.get("code") != "Ok" or not route_data.get("routes"):
        raise HTTPException(
            status_code=404,
            detail="No driving route could be found between these locations.",
        )

    route = route_data["routes"][0]

    return {
        "origin": {
            "name": start.get("name"),
            "state": start.get("admin1"),
            "latitude": start["latitude"],
            "longitude": start["longitude"],
        },
        "destination": {
            "name": end.get("name"),
            "state": end.get("admin1"),
            "latitude": end["latitude"],
            "longitude": end["longitude"],
        },
        "route": {
            "distance_km": round(route["distance"] / 1000, 2),
            "estimated_duration_minutes": round(route["duration"] / 60, 1),
            "estimated_duration_hours": round(route["duration"] / 3600, 2),
            "profile": "driving",
        },
        "source": "OSRM",
        "source_url": "https://project-osrm.org/",
        "notice": (
            "Distance and duration are estimates. Actual travel time "
            "may vary with traffic, road conditions, and stops."
        ),
    }

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
    try:
        return discover_places(
            destination=destination,
            category=category,
            radius_m=radius_m,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Place discovery is temporarily unavailable. "
                "Please try again later."
            ),
        ) from exc
# ---------------------------------------------------------
# INITIAL TRIP PLANNING
# ---------------------------------------------------------

@app.post("/api/trips/plan")
def create_plan(trip: TripRequest):
    request_data = trip.model_dump(mode="json")
        # Discover real attractions and restaurants for the destination.
    discovered_places = []

    try:
        discovery_result = discover_places(
            destination=trip.destination,
            category="both",
            radius_m=7000,
            limit=30,
        )

        discovered_places = discovery_result.get("places", [])

    except Exception as exc:
        # Keep trip planning available if the public discovery service fails.
        print(f"Place discovery unavailable: {exc}")

    # Generate the itinerary using real places when available.
    itinerary = generate_itinerary(
        trip.model_dump(),
        places=discovered_places,
    )

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