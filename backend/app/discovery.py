import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


# ============================================================
# Configuration
# ============================================================

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"

REQUEST_TIMEOUT = 20
MAX_RADIUS_M = 50000
MAX_LIMIT = 50

ALLOWED_CATEGORIES = {"attractions", "restaurants", "both"}

ATTRACTION_CATEGORIES = [
    "tourism.attraction",
    "entertainment.museum",
]

RESTAURANT_CATEGORIES = [
    "catering.restaurant",
    "catering.cafe",
]

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "AdaptiveTrip/1.0",
        "Accept": "application/json",
    }
)

# Names that are clearly not useful standalone travel destinations.
INVALID_NAME_PATTERN = re.compile(
    r"""
    \b(
        road|street|highway|expressway|lane|bylane|
        flyover|underpass|overpass|intersection|junction|
        roundabout|service\s+road|main\s+road|
        bus\s+stop|railway\s+line|platform
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

GENERIC_NAMES = {
    "",
    "unnamed place",
    "unknown",
    "unknown place",
    "yes",
    "no",
    "restaurant",
    "cafe",
    "attraction",
    "building",
}


# ============================================================
# Common Helpers
# ============================================================

def _error_response(
    destination: str,
    category: str = "both",
    radius_m: int = 7000,
    message: str = "Place discovery failed.",
    resolved_location: Optional[str] = None,
    center: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    return {
        "success": False,
        "destination": destination,
        "resolved_location": resolved_location or destination,
        "center": center,
        "radius_m": radius_m,
        "category": category,
        "count": 0,
        "places": [],
        "data_notes": [
            message,
            "Check the backend terminal for diagnostic details.",
            "No live places are included in this response.",
        ],
    }


def _calculate_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate the Haversine distance between two coordinates."""

    earth_radius_km = 6371.0

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2) ** 2
    )

    a = min(1.0, max(0.0, a))

    return round(
        earth_radius_km
        * 2
        * math.atan2(math.sqrt(a), math.sqrt(1 - a)),
        3,
    )


def _get_coordinates(
    destination: str,
) -> Tuple[float, float, str]:
    """Resolve a destination using Open-Meteo geocoding."""

    params = {
        "name": destination,
        "count": 5,
        "language": "en",
        "format": "json",
    }

    try:
        response = SESSION.get(
            GEOCODE_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    except requests.exceptions.RequestException as exc:
        print("Geocoding request failed:", str(exc))
        raise RuntimeError(
            "Could not connect to the destination geocoding service."
        ) from exc

    except ValueError as exc:
        print("Geocoding returned invalid JSON.")
        raise RuntimeError(
            "The geocoding service returned invalid JSON."
        ) from exc

    results = data.get("results") or []

    if not results:
        raise ValueError(
            f"No coordinates found for destination: {destination}"
        )

    selected = next(
        (
            item
            for item in results
            if item.get("name", "").casefold()
            == destination.casefold()
        ),
        results[0],
    )

    latitude = float(selected["latitude"])
    longitude = float(selected["longitude"])

    location_parts = [
        selected.get("name"),
        selected.get("admin1"),
        selected.get("country"),
    ]

    resolved_location = ", ".join(
        dict.fromkeys(
            part for part in location_parts if part
        )
    )

    return latitude, longitude, resolved_location


# ============================================================
# Place Filtering
# ============================================================

def _is_valid_place_name(name: str) -> bool:
    """Reject generic labels and obvious road-related results."""

    cleaned_name = " ".join((name or "").split())
    normalized = cleaned_name.casefold().strip(" .,;:-")

    if normalized in GENERIC_NAMES:
        return False

    if len(cleaned_name) < 2:
        return False

    if INVALID_NAME_PATTERN.search(cleaned_name):
        return False

    return True


def _classify_place(
    categories: List[str],
    requested_type: str,
) -> Optional[str]:
    """
    Classify a place only when its categories match the request.

    Do not classify every returned feature as a restaurant simply
    because the Geoapify request included restaurant categories.
    """

    normalized_categories = {
        str(item).strip().casefold()
        for item in categories
        if item
    }

    is_restaurant = any(
        category.startswith("catering.restaurant")
        or category.startswith("catering.cafe")
        or category.startswith("catering.fast_food")
        or category.startswith("catering.food_court")
        for category in normalized_categories
    )

    is_attraction = any(
        category.startswith("tourism.attraction")
        or category.startswith("entertainment.museum")
        for category in normalized_categories
    )

    if requested_type == "restaurants":
        return "restaurant" if is_restaurant else None

    if requested_type == "attractions":
        return "attraction" if is_attraction else None

    if is_restaurant:
        return "restaurant"

    if is_attraction:
        return "attraction"

    return None


# ============================================================
# Geoapify Normalization
# ============================================================

def _normalize_place(
    feature: Dict[str, Any],
    center_lat: float,
    center_lon: float,
    requested_type: str,
) -> Optional[Dict[str, Any]]:
    """Normalize and validate a Geoapify feature."""

    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []

    if len(coordinates) < 2:
        return None

    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None

    if not (-90 <= latitude <= 90):
        return None

    if not (-180 <= longitude <= 180):
        return None

    raw_categories = properties.get("categories") or []

    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]

    categories = [
        str(item)
        for item in raw_categories
        if item
    ]

    # Require actual category evidence, not merely the query type.
    place_category = _classify_place(
        categories,
        requested_type,
    )

    if place_category is None:
        return None

    name = (
        properties.get("name")
        or properties.get("address_line1")
        or ""
    )

    # Reject road names even when Geoapify labels the feature
    # with an unexpected catering category.
    if not _is_valid_place_name(name):
        return None

    address = (
        properties.get("formatted")
        or properties.get("address_line2")
        or properties.get("address_line1")
        or ""
    )

    place_id = (
        properties.get("place_id")
        or f"{latitude:.6f},{longitude:.6f}"
    )

    contact = properties.get("contact") or {}
    website = properties.get("website") or contact.get("website")
    phone = properties.get("phone") or contact.get("phone")

    distance_km = _calculate_distance_km(
        center_lat,
        center_lon,
        latitude,
        longitude,
    )

    # A second radius check protects against unexpected API results.
    if distance_km * 1000 > properties.get(
        "requested_radius_m",
        MAX_RADIUS_M,
    ):
        return None

    map_url = (
        "https://www.google.com/maps/search/?api=1&query="
        f"{latitude},{longitude}"
    )

    return {
        "place_id": str(place_id),
        "name": str(name).strip(),
        "category": place_category,
        "place_type": next(
            (
                item
                for item in categories
                if item.startswith(
                    ("catering.", "tourism.", "entertainment.")
                )
            ),
            place_category,
        ),
        "latitude": latitude,
        "longitude": longitude,
        "address": address,
        "cuisine": properties.get("catering", {}).get("cuisine"),
        "website": website,
        "opening_hours": properties.get("opening_hours"),
        "phone": phone,
        "distance_km": distance_km,
        "map_url": map_url,
        "data_source": "Geoapify",
        "categories": categories,
    }


# ============================================================
# Geoapify Requests
# ============================================================

def _fetch_places(
    api_key: str,
    center_lat: float,
    center_lon: float,
    radius_m: int,
    limit: int,
    requested_type: str,
) -> List[Dict[str, Any]]:
    """Fetch one type of place and return validated results."""

    if requested_type == "attractions":
        categories = ATTRACTION_CATEGORIES
    else:
        categories = RESTAURANT_CATEGORIES

    params = {
        "categories": ",".join(categories),
        "filter": (
            f"circle:{center_lon},{center_lat},{radius_m}"
        ),
        "bias": f"proximity:{center_lon},{center_lat}",
        "limit": limit,
        "lang": "en",
        "apiKey": api_key,
    }

    try:
        response = SESSION.get(
            GEOAPIFY_PLACES_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            f"Geoapify {requested_type} HTTP status:",
            response.status_code,
        )

        if not response.ok:
            # Do not print the request URL because it contains the API key.
            print(
                f"Geoapify {requested_type} response:",
                response.text[:1500],
            )

        response.raise_for_status()
        data = response.json()

    except requests.exceptions.RequestException as exc:
        print(
            f"Geoapify {requested_type} request failed:",
            str(exc),
        )
        raise RuntimeError(
            f"Geoapify {requested_type} request failed."
        ) from exc

    except ValueError as exc:
        print(
            f"Geoapify {requested_type} returned invalid JSON."
        )
        raise RuntimeError(
            f"Geoapify returned invalid JSON for {requested_type}."
        ) from exc

    features = data.get("features") or []
    places = []

    for feature in features:
        if not isinstance(feature, dict):
            continue

        place = _normalize_place(
            feature=feature,
            center_lat=center_lat,
            center_lon=center_lon,
            requested_type=requested_type,
        )

        if place is not None:
            # Enforce the caller's actual requested radius.
            if place["distance_km"] * 1000 <= radius_m:
                places.append(place)

    print(
        f"Geoapify {requested_type}: "
        f"{len(features)} raw results, {len(places)} valid places."
    )

    return places


# ============================================================
# Deduplication and Category Balancing
# ============================================================

def _deduplicate_places(
    places: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove duplicate records by ID and near-identical coordinates."""

    unique_places = []
    seen_ids = set()
    seen_coordinates = set()

    for place in places:
        place_id = place["place_id"]

        if place_id in seen_ids:
            continue

        # Helps catch duplicates returned with different IDs.
        coordinate_key = (
            round(place["latitude"], 5),
            round(place["longitude"], 5),
            place["category"],
            place["name"].casefold().strip(),
        )

        if coordinate_key in seen_coordinates:
            continue

        seen_ids.add(place_id)
        seen_coordinates.add(coordinate_key)
        unique_places.append(place)

    return unique_places


def _balance_categories(
    attractions: List[Dict[str, Any]],
    restaurants: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Return a balanced selection for category='both'.

    Aim for half attractions and half restaurants. If one type has
    fewer results, fill remaining slots from the other type.
    """

    attraction_target = (limit + 1) // 2
    restaurant_target = limit // 2

    selected_attractions = attractions[:attraction_target]
    selected_restaurants = restaurants[:restaurant_target]

    selected = (
        selected_attractions
        + selected_restaurants
    )

    selected_ids = {
        place["place_id"]
        for place in selected
    }

    remaining = [
        place
        for place in attractions + restaurants
        if place["place_id"] not in selected_ids
    ]

    remaining.sort(
        key=lambda place: place["distance_km"]
    )

    selected.extend(
        remaining[: max(0, limit - len(selected))]
    )

    selected.sort(
        key=lambda place: place["distance_km"]
    )

    return selected[:limit]


# ============================================================
# Public Function Used by FastAPI
# ============================================================

def discover_places(
    destination: str,
    category: str = "both",
    radius_m: int = 7000,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Discover attractions and restaurants around a destination.

    This function preserves the existing API response structure.
    """

    destination = (destination or "").strip()
    category = (category or "both").strip().lower()

    try:
        radius_m = int(radius_m)
        limit = int(limit)
    except (TypeError, ValueError):
        return _error_response(
            destination,
            category,
            message="Radius and limit must be valid integers.",
        )

    if not destination:
        return _error_response(
            destination,
            category,
            message="A destination is required.",
        )

    if category not in ALLOWED_CATEGORIES:
        return _error_response(
            destination,
            category,
            message=(
                "Invalid category. Use attractions, restaurants, or both."
            ),
        )

    if radius_m <= 0 or limit <= 0:
        return _error_response(
            destination,
            category,
            message="Radius and limit must be greater than zero.",
        )

    radius_m = min(radius_m, MAX_RADIUS_M)
    limit = min(limit, MAX_LIMIT)

    api_key = os.getenv("GEOAPIFY_API_KEY", "").strip()

    if not api_key:
        print("Geoapify API key not found.")
        print("Expected environment file:", ENV_PATH)

        return _error_response(
            destination,
            category,
            radius_m,
            "Geoapify API key is missing from backend/.env.",
        )

    try:
        center_lat, center_lon, resolved_location = (
            _get_coordinates(destination)
        )
    except (RuntimeError, ValueError) as exc:
        print("Destination resolution failed:", str(exc))

        return _error_response(
            destination,
            category,
            radius_m,
            str(exc),
        )

    center = {
        "lat": center_lat,
        "lon": center_lon,
    }

    try:
        if category == "attractions":
            places = _fetch_places(
                api_key,
                center_lat,
                center_lon,
                radius_m,
                limit,
                "attractions",
            )

        elif category == "restaurants":
            places = _fetch_places(
                api_key,
                center_lat,
                center_lon,
                radius_m,
                limit,
                "restaurants",
            )

        else:
            # Separate requests prevent restaurants from crowding out
            # attractions when both types are requested.
            attractions = _fetch_places(
                api_key,
                center_lat,
                center_lon,
                radius_m,
                limit,
                "attractions",
            )

            restaurants = _fetch_places(
                api_key,
                center_lat,
                center_lon,
                radius_m,
                limit,
                "restaurants",
            )

            attractions = _deduplicate_places(attractions)
            restaurants = _deduplicate_places(restaurants)

            places = _balance_categories(
                attractions,
                restaurants,
                limit,
            )

    except RuntimeError as exc:
        print("Place discovery failed:", str(exc))

        return _error_response(
            destination=destination,
            category=category,
            radius_m=radius_m,
            message=str(exc),
            resolved_location=resolved_location,
            center=center,
        )

    places = _deduplicate_places(places)

    places.sort(
        key=lambda place: place["distance_km"]
    )

    places = places[:limit]

    category_counts = {
        "attractions": sum(
            place["category"] == "attraction"
            for place in places
        ),
        "restaurants": sum(
            place["category"] == "restaurant"
            for place in places
        ),
    }

    data_notes = [
        "Place data retrieved from Geoapify.",
        "Distances are calculated from the destination coordinates.",
        "Road-like names and unrelated categories are filtered out.",
        "Duplicate place records are removed.",
    ]

    if category == "both":
        data_notes.append(
            "Attractions and restaurants are selected separately "
            "to improve category balance."
        )

    if not places:
        data_notes.append(
            "No valid matching places were found within the requested radius."
        )

    print(
        f"Discovery completed for {destination}: "
        f"{len(places)} places; "
        f"{category_counts['attractions']} attractions; "
        f"{category_counts['restaurants']} restaurants."
    )

    return {
        "success": True,
        "destination": destination,
        "resolved_location": resolved_location,
        "center": center,
        "radius_m": radius_m,
        "category": category,
        "count": len(places),
        "places": places,
        "data_notes": data_notes,
    }