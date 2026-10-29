from datetime import timedelta


OPTIONS = {
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

COSTS = {
    "Budget-friendly": [250, 350, 250],
    "Balanced": [600, 800, 600],
    "Comfort": [1200, 1600, 1200],
}

TIMES = ["09:00", "12:00", "16:00"]
DURATIONS = [120, 90, 120]


def generate_itinerary(trip):
    days = (trip["endDate"] - trip["startDate"]).days + 1

    interests = [
        interest
        for interest in trip.get("interests", [])
        if interest in OPTIONS
    ] or ["History", "Food", "Nature"]

    costs = COSTS.get(
        trip.get("travelStyle", "Balanced"),
        COSTS["Balanced"],
    )

    result = []

    for n in range(1, days + 1):
        titles = [
            OPTIONS[interest][(n + j - 1) % 3]
            for j, interest in enumerate(interests[:3])
        ]

        fallback = [
            "Explore the surrounding area",
            "Take a meal break and rest",
            "Enjoy flexible leisure time",
        ]

        titles += fallback[len(titles):]

        activities = []

        for i, title in enumerate(titles[:3]):
            outdoor = any(
                word in title.lower()
                for word in [
                    "nature",
                    "scenic",
                    "viewpoint",
                    "outdoor",
                    "walk",
                ]
            )

            activities.append({
                "time": TIMES[i],
                "duration_minutes": DURATIONS[i],
                "title": title,
                "estimated_cost": costs[i] * trip["travelers"],
                "category": "outdoor" if outdoor else "indoor",
            })

        result.append({
            "day": n,
            "date": (
                trip["startDate"] + timedelta(days=n - 1)
            ).isoformat(),
            "destination": trip["destination"],
            "activities": activities,
            "estimated_daily_cost": sum(
                activity["estimated_cost"]
                for activity in activities
            ),
        })

    return result


def validate_itinerary(itinerary, budget):
    errors = []
    warnings = []
    total = 0

    for day in itinerary:
        activities = day.get("activities", [])

        day["estimated_daily_cost"] = sum(
            activity.get("estimated_cost", 0)
            for activity in activities
        )

        total += day["estimated_daily_cost"]

        ordered_activities = sorted(
            activities,
            key=lambda activity: activity.get("time", ""),
        )

        for activity in ordered_activities:
            try:
                hour, minute = map(
                    int,
                    activity["time"].split(":"),
                )

                if not (
                    0 <= hour <= 23
                    and 0 <= minute <= 59
                ):
                    raise ValueError

            except (ValueError, KeyError, AttributeError):
                errors.append(
                    f"Day {day.get('day')}: invalid time "
                    f"{activity.get('time')}"
                )

            duration = activity.get("duration_minutes", 0)

            if (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or duration <= 0
            ):
                errors.append(
                    f"Day {day.get('day')}: invalid duration"
                )

        for first, second in zip(
            ordered_activities,
            ordered_activities[1:],
        ):
            try:
                first_hour, first_minute = map(
                    int,
                    first["time"].split(":"),
                )

                second_hour, second_minute = map(
                    int,
                    second["time"].split(":"),
                )

                first_duration = first["duration_minutes"]

                if (
                    first_hour * 60
                    + first_minute
                    + first_duration
                    > second_hour * 60 + second_minute
                ):
                    errors.append(
                        f"Day {day.get('day')}: "
                        "overlapping activities"
                    )

            except (ValueError, KeyError, TypeError, AttributeError):
                # The invalid time or duration is reported above.
                pass

    if total > budget:
        errors.append(
            f"Estimated trip cost exceeds budget by "
            f"Rs. {round(total - budget, 2)}."
        )

    warnings.append(
        "Opening hours, route travel times and live prices "
        "are not verified."
    )

    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "estimated_total_cost": total,
        "budget": budget,
        "remaining_budget": round(budget - total, 2),
    }


def minimal_change_replan(itinerary, evidence, travelers):
    """
    Replace only the affected activity.

    This function preserves the original itinerary structure and
    recalculates daily estimates. It does not guarantee that the
    complete trip fits the budget; validate_itinerary() checks that.
    """

    updated = [
        {
            **day,
            "activities": [
                activity.copy()
                for activity in day["activities"]
            ],
        }
        for day in itinerary
    ]

    day_index = evidence["affected_day"] - 1
    activity_index = evidence["affected_activity_index"]

    if day_index < 0 or day_index >= len(updated):
        raise ValueError("affected_day is outside trip")

    if (
        activity_index < 0
        or activity_index >= len(
            updated[day_index]["activities"]
        )
    ):
        raise ValueError("Invalid activity index")

    activity = updated[day_index]["activities"][activity_index]

    old_title = activity["title"]
    old_cost = activity["estimated_cost"]

    disruption_type = evidence["disruption_type"]

    replacements = {
        "weather": {
            "title": "Indoor cultural activity (weather alternative)",
            "category": "indoor",
            "cost_per_traveler": 500,
        },
        "closure": {
            "title": "Explore an alternative local attraction",
            "category": "indoor",
            "cost_per_traveler": 400,
        },
        "transport": {
            "title": "Nearby activity to reduce transport dependency",
            "category": "outdoor",
            "cost_per_traveler": 450,
        },
    }

    if disruption_type not in replacements:
        raise ValueError("Unsupported disruption type")

    replacement = replacements[disruption_type]

    new_cost = min(
        old_cost,
        replacement["cost_per_traveler"] * travelers,
    )

    activity.update({
        "title": replacement["title"],
        "category": replacement["category"],
        "estimated_cost": new_cost,
    })

    for day in updated:
        day["estimated_daily_cost"] = sum(
            item["estimated_cost"]
            for item in day["activities"]
        )

    changes = [{
        "day": day_index + 1,
        "activity_index": activity_index,
        "old_activity": old_title,
        "new_activity": replacement["title"],
        "old_cost": old_cost,
        "new_cost": new_cost,
        "reason": (
            f"Replaced after {disruption_type} evidence "
            "passed the prototype policy."
        ),
    }]

    return updated, changes

def repair_itinerary_budget(
    itinerary,
    budget,
    minimum_activity_cost=100,
):
    """
    Reduce estimated activity costs without allowing them
    to fall below a configured minimum.

    This is a prototype constraint, not a verified real-world
    price model. Activity costs should eventually be based on
    actual alternative activities and their estimated prices.
    """

    if budget < 0:
        raise ValueError("Budget cannot be negative.")

    if minimum_activity_cost < 0:
        raise ValueError("Minimum activity cost cannot be negative.")

    updated = [
        {
            **day,
            "activities": [
                activity.copy()
                for activity in day["activities"]
            ],
        }
        for day in itinerary
    ]

    def calculate_total():
        return sum(
            activity["estimated_cost"]
            for day in updated
            for activity in day["activities"]
        )

    original_total = calculate_total()

    if original_total <= budget:
        return updated, []

    # Calculate the minimum possible total under this constraint.
    minimum_total = sum(
        min(
            activity["estimated_cost"],
            minimum_activity_cost,
        )
        for day in updated
        for activity in day["activities"]
    )

    if minimum_total > budget:
        raise ValueError(
            "The requested budget cannot be satisfied under "
            "the configured minimum activity cost constraint. "
            f"Minimum estimated total: {minimum_total}; "
            f"requested budget: {budget}."
        )

    excess = original_total - budget
    changes = []

    # Change the most expensive estimates first.
    candidates = sorted(
        (
            (day_index, activity_index, activity)
            for day_index, day in enumerate(updated)
            for activity_index, activity in enumerate(day["activities"])
        ),
        key=lambda item: item[2]["estimated_cost"],
        reverse=True,
    )

    for day_index, activity_index, activity in candidates:
        if excess <= 0:
            break

        old_cost = activity["estimated_cost"]

        # Never reduce an estimate below the configured minimum.
        floor_cost = min(old_cost, minimum_activity_cost)
        available_reduction = old_cost - floor_cost

        if available_reduction <= 0:
            continue

        reduction = min(available_reduction, excess)
        new_cost = old_cost - reduction

        activity["estimated_cost"] = new_cost
        excess -= reduction

        changes.append({
            "day": updated[day_index]["day"],
            "activity_index": activity_index,
            "activity": activity["title"],
            "old_cost": old_cost,
            "new_cost": new_cost,
            "reason": (
                "Adjusted estimated cost within the configured "
                "minimum-cost constraint."
            ),
        })

    for day in updated:
        day["estimated_daily_cost"] = sum(
            activity["estimated_cost"]
            for activity in day["activities"]
        )

    final_total = calculate_total()

    if final_total > budget:
        raise ValueError(
            "Unable to satisfy the requested budget under "
            "the configured minimum activity cost constraint."
        )

    return updated, changes

