
from datetime import date, timedelta
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

app = FastAPI(
    title="TripPilot AI",
    description="Agentic AI-based Dynamic Travel Planning and Replanning System",
    version="1.0.0",
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


class TripRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=150)
    startDate: date
    endDate: date
    budget: float = Field(gt=0)
    travelers: int = Field(ge=1, le=10)
    interests: List[str] = Field(default_factory=list)
    travelStyle: str = "Balanced"

    @model_validator(mode="after")
    def validate_trip(self):
        if self.endDate < self.startDate:
            raise ValueError("End date must be on or after the start date")

        if (self.endDate - self.startDate).days > 30:
            raise ValueError("Trips can be at most 31 days in this prototype")

        return self


ACTIVITY_OPTIONS = {
    "Nature": [
        "Explore a nature spot or city garden",
        "Enjoy a scenic walk",
        "Visit a local viewpoint",
    ],
    "Adventure": [
        "Explore a local outdoor activity",
        "Plan an adventure experience",
        "Try a suitable guided activity",
    ],
    "History": [
        "Explore a historical landmark",
        "Visit a museum or heritage site",
        "Discover the local heritage area",
    ],
    "Food": [
        "Explore local cuisine",
        "Visit a popular food area",
        "Try regional dishes",
    ],
    "Shopping": [
        "Explore a local market",
        "Visit a shopping district",
        "Browse local crafts and souvenirs",
    ],
    "Relaxation": [
        "Enjoy a relaxed morning",
        "Schedule free time at a peaceful spot",
        "Keep the afternoon flexible",
    ],
}

# Illustrative per-person estimates in INR.
# These are prototype assumptions, not live prices.
STYLE_COSTS = {
    "Budget-friendly": [250, 350, 250],
    "Balanced": [600, 800, 600],
    "Comfort": [1200, 1600, 1200],
}


def choose_activities(interests: List[str], day_number: int):
    selected = [item for item in interests if item in ACTIVITY_OPTIONS]

    if not selected:
        selected = ["History", "Food", "Nature"]

    activities = []

    for index, interest in enumerate(selected[:3]):
        options = ACTIVITY_OPTIONS[interest]
        activities.append(options[(day_number + index - 1) % len(options)])

    while len(activities) < 3:
        activities.append(
            [
                "Explore the surrounding area",
                "Take a meal break and rest",
                "Enjoy flexible leisure time",
            ][len(activities)]
        )

    return activities[:3]


def generate_itinerary(trip: TripRequest):
    total_days = (trip.endDate - trip.startDate).days + 1
    unit_costs = STYLE_COSTS.get(trip.travelStyle, STYLE_COSTS["Balanced"])
    itinerary = []

    for day_number in range(1, total_days + 1):
        current_date = trip.startDate + timedelta(days=day_number - 1)
        activity_titles = choose_activities(trip.interests, day_number)

        activities = []

        for index, title in enumerate(activity_titles):
            estimated_cost = unit_costs[index] * trip.travelers

            activities.append(
                {
                    "time": ["09:00", "12:00", "16:00"][index],
                    "duration_minutes": [120, 90, 120][index],
                    "title": title,
                    "estimated_cost": estimated_cost,
                }
            )

        daily_cost = sum(item["estimated_cost"] for item in activities)

        itinerary.append(
            {
                "day": day_number,
                "date": current_date.isoformat(),
                "destination": trip.destination,
                "activities": activities,
                "estimated_daily_cost": daily_cost,
            }
        )

    return itinerary


def validate_itinerary(itinerary, total_budget):
    errors = []
    warnings = []
    total_cost = sum(day["estimated_daily_cost"] for day in itinerary)

    # Check whether the estimated trip cost exceeds the user's budget.
    if total_cost > total_budget:
        errors.append(
            f"Estimated trip cost exceeds budget by ₹{total_cost - total_budget}."
        )

    # Check each day's activity times and durations.
    for day in itinerary:
        seen_times = set()

        for activity in day["activities"]:
            time_value = activity["time"]

            if time_value in seen_times:
                errors.append(
                    f"Day {day['day']} has duplicate activity start time {time_value}."
                )

            seen_times.add(time_value)

            if activity["duration_minutes"] <= 0:
                errors.append(
                    f"Day {day['day']} has an activity with invalid duration."
                )

        ordered = sorted(day["activities"], key=lambda item: item["time"])

        for previous, current in zip(ordered, ordered[1:]):
            previous_hour, previous_minute = map(
                int, previous["time"].split(":")
            )
            current_hour, current_minute = map(
                int, current["time"].split(":")
            )

            previous_end = (
                previous_hour * 60
                + previous_minute
                + previous["duration_minutes"]
            )
            current_start = current_hour * 60 + current_minute

            if previous_end > current_start:
                errors.append(
                    f"Day {day['day']} has overlapping activities."
                )

    if not errors:
        warnings.append(
            "Attraction opening hours, route travel time, and live prices are not verified."
        )

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "estimated_total_cost": total_cost,
        "budget": total_budget,
        "remaining_budget": round(total_budget - total_cost, 2),
    }


@app.get("/")
def home():
    return {
        "project": "TripPilot AI",
        "status": "running",
        "message": "Welcome to TripPilot AI Backend",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "TripPilot AI API",
    }


@app.post("/api/trips/plan")
def create_trip_plan(trip: TripRequest):
    total_days = (trip.endDate - trip.startDate).days + 1
    itinerary = generate_itinerary(trip)
    validation = validate_itinerary(itinerary, trip.budget)

    return {
        "success": True,
        "message": "Prototype itinerary generated",
        "trip": {
            "destination": trip.destination,
            "start_date": trip.startDate.isoformat(),
            "end_date": trip.endDate.isoformat(),
            "trip_days": total_days,
            "budget": trip.budget,
            "currency": "INR",
            "travelers": trip.travelers,
            "interests": trip.interests,
            "travel_style": trip.travelStyle,
        },
        "itinerary": itinerary,
        "validation": validation,
        "planning_notes": [
            "Activities are illustrative suggestions, not verified attractions.",
            "Activity costs use fixed prototype assumptions per person and travel style.",
            "Opening hours, route travel time, and live prices are not verified.",
        ],
    }

from typing import Literal


class ReplanRequest(BaseModel):
    trip: TripRequest
    scenario: Literal["weather", "closure", "budget"]
    affected_day: int = Field(default=1, ge=1, le=31)
    affected_activity_index: int = Field(default=0, ge=0, le=2)
    new_budget: float | None = Field(default=None, gt=0)


def replan_itinerary(request: ReplanRequest):
    trip = request.trip
    original = generate_itinerary(trip)

    if request.affected_day > len(original):
        raise ValueError("Affected day is outside the trip dates")

    if request.scenario == "budget" and request.new_budget is None:
        raise ValueError("new_budget is required for budget replanning")

    updated = [
        {
            **day,
            "activities": [activity.copy() for activity in day["activities"]],
        }
        for day in original
    ]

    changes = []
    day = updated[request.affected_day - 1]
    activity = day["activities"][request.affected_activity_index]

    if request.scenario == "weather":
        old_title = activity["title"]
        activity["title"] = "Indoor cultural activity (weather alternative)"
        activity["estimated_cost"] = min(activity["estimated_cost"], 500 * trip.travelers)

        changes.append({
            "day": request.affected_day,
            "activity_index": request.affected_activity_index,
            "old_activity": old_title,
            "new_activity": activity["title"],
            "reason": "Weather scenario: replace the selected activity with an indoor alternative.",
        })

    elif request.scenario == "closure":
        old_title = activity["title"]
        activity["title"] = "Explore an alternative local attraction"
        activity["estimated_cost"] = min(activity["estimated_cost"], 400 * trip.travelers)

        changes.append({
            "day": request.affected_day,
            "activity_index": request.affected_activity_index,
            "old_activity": old_title,
            "new_activity": activity["title"],
            "reason": "Closure scenario: replace the unavailable attraction.",
        })

    elif request.scenario == "budget":
        # Prototype policy: switch to lower-cost assumptions for the whole trip.
        # These are illustrative estimates, not live prices.
        new_budget = request.new_budget
        low_cost_trip = trip.model_copy(
            update={
                "budget": new_budget,
                "travelStyle": "Budget-friendly",
            }
        )
        updated = generate_itinerary(low_cost_trip)

        changes.append({
            "day": None,
            "activity_index": None,
            "old_activity": None,
            "new_activity": None,
            "reason": "Budget scenario: regenerated the itinerary using budget-friendly cost assumptions.",
        })

    for day_item in updated:
        day_item["estimated_daily_cost"] = sum(
            item["estimated_cost"] for item in day_item["activities"]
        )

    effective_budget = (
        request.new_budget
        if request.scenario == "budget"
        else trip.budget
    )

    validation = validate_itinerary(updated, effective_budget)

    return {
        "success": True,
        "scenario": request.scenario,
        "original_itinerary": original,
        "replanned_itinerary": updated,
        "changes": changes,
        "validation": validation,
        "notes": [
            "Scenarios are simulated; no live weather or closure data is checked.",
            "Alternative activities are illustrative suggestions, not verified attractions.",
            "Budget estimates are prototype assumptions, not live prices.",
        ],
    }


@app.post("/api/trips/replan")
def create_replan(request: ReplanRequest):
    return replan_itinerary(request)
