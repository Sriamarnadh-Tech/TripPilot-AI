import os
from typing import Any, Dict, List, Optional

import requests


GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"

REQUEST_TIMEOUT = 20

ATTRACTION_CATEGORIES = [
    "tourism.attraction",
    "tourism.sights",
    "entertainment.museum",
    "entertainment.zoo",
    "entertainment.theme_park",
    "entertainment.aquarium",
]

RESTAURANT_CATEGORIES = [
    "catering.restaurant",
    "catering.cafe",
    "catering.fast_food",
    "catering.food_court",
]


def _get_api_key() -> str:
    """Get the Geoapify API key from the backend environment."""

    key = (
        os.getenv("ADAPTIVETRIP_GEOAPIFY_API_KEY")
        or os.getenv("GEOAPIFY_API_KEY")
    )

    if not key:
        raise ValueError(
            "Geoapify API key is missing. Set "
            "ADAPTIVETRIP_GEOAPIFY_API_KEY in your environment."
        )

    return key.strip()


def _geocode_destination(
    destination: str,
    api_key: str,
) -> Dict[str, Any]:
    """Convert a destination name into geographic coordinates."""

    destination = destination.strip()

    if not destination:
        raise ValueError("Destination cannot be empty.")

    query = destination

    # TripPilot currently targets travel planning in India.
    if "india" not in destination.lower():
        query = f"{destination}, India"

    response = requests.get(
        GEOCODE_URL,
        params={
            "text": query,
            "format": "json",
            "limit": 1,
            "apiKey": api_key,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    payload = response.json()
    results = payload.get("results", [])

    if not results:
        raise LookupError(
            f"Could not find destination '{destination}'. "
            "Try including the city, state, or country."
        )

    result = results[0]

    lat = result.get("lat")
    lon = result.get("lon")

    if lat is None or lon is None:
        raise LookupError(
            f"Coordinates were not returned for '{destination}'."
        )

    return {
        "lat": float(lat),
        "lon": float(lon),
        "formatted": result.get("formatted") or query,
        "city": result.get("city"),
        "state": result.get("state"),
        "country": result.get("country"),
    }


def _first_value(*values: Any) -> Optional[str]:
    """Return the first non-empty value."""

    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()

    return None


def _classify_place(
    categories: List[str],
    requested_category: str,
) -> str:
    """Classify a discovered place for the frontend."""

    category_text = " ".join(categories).lower()

    restaurant_markers = [
        "catering.restaurant",
        "catering.cafe",
        "catering.fast_food",
        "catering.food_court",
        "catering.ice_cream",
    ]

    if any(marker in category_text for marker in restaurant_markers):
        return "restaurant"

    if requested_category == "restaurants":
        return "restaurant"

    return "attraction"


def _extract_cuisine(
    properties: Dict[str, Any],
) -> Optional[str]:
    """Extract cuisine when the provider supplies it."""

    datasource = properties.get("datasource") or {}
    raw = datasource.get("raw") or {}

    return _first_value(
        properties.get("catering.cuisine"),
        properties.get("cuisine"),
        raw.get("cuisine"),
    )


def _normalize_place(
    feature: Dict[str, Any],
    requested_category: str,
) -> Optional[Dict[str, Any]]:
    """Normalize a Geoapify feature into AdaptiveTrip's data format."""

    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}

    coordinates = geometry.get("coordinates") or []

    lon = properties.get("lon")
    lat = properties.get("lat")

    # GeoJSON coordinate order is longitude, latitude.
    if (lon is None or lat is None) and len(coordinates) >= 2:
        lon = coordinates[0]
        lat = coordinates[1]

    name = _first_value(
        properties.get("name"),
        properties.get("address_line1"),
    )

    if not name or lon is None or lat is None:
        return None

    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return None

    categories = properties.get("categories") or []

    if isinstance(categories, str):
        categories = [categories]

    place_type = _classify_place(
        categories,
        requested_category,
    )

    category_label = (
        "Restaurant" if place_type == "restaurant" else "Attraction"
    )

    address = _first_value(
        properties.get("formatted"),
        properties.get("address_line2"),
        properties.get("address_line1"),
    )

    website = _first_value(
        properties.get("website"),
        properties.get("contact.website"),
    )

    # Construct a map link using the actual coordinates.
    map_url = (
        "https://www.openstreetmap.org/"
        f"?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"
    )

    place_id = _first_value(properties.get("place_id"))

    return {
        "id": place_id or f"{lat:.6f}_{lon:.6f}",
        "name": name,
        "category": category_label,
        "place_type": place_type,
        "address": address or "Address not available",
        "cuisine": _extract_cuisine(properties),
        "opening_hours": _first_value(
            properties.get("opening_hours")
        ),
        "price_level": None,
        "rating": None,
        "map_url": map_url,
        "source_url": map_url,
        "website": website,
        "latitude": lat,
        "longitude": lon,
        "distance_m": properties.get("distance"),
        "provider_categories": categories,
        "data_source": "Geoapify",
        "rating_count": None,
        "open_now": None,
    }


def _fetch_places(
    api_key: str,
    lat: float,
    lon: float,
    radius_m: int,
    categories: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Retrieve places near the specified coordinates."""

    response = requests.get(
        PLACES_URL,
        params={
            "categories": ",".join(categories),
            "filter": f"circle:{lon},{lat},{radius_m}",
            "bias": f"proximity:{lon},{lat}",
            "limit": limit,
            "lang": "en",
            "apiKey": api_key,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    payload = response.json()
    features = payload.get("features", [])

    if not isinstance(features, list):
        return []

    return features


def discover_places(
    destination: str,
    category: str = "both",
    radius_m: int = 7000,
    limit: int = 30,
) -> Dict[str, Any]:
    """
    Discover attractions and food places around an Indian destination.

    Supported categories:
        both
        attractions
        restaurants
    """

    category = (category or "both").strip().lower()

    valid_categories = {
        "both",
        "attractions",
        "restaurants",
    }

    if category not in valid_categories:
        raise ValueError(
            "Invalid category. Use 'both', 'attractions', or 'restaurants'."
        )

    if not 100 <= radius_m <= 50000:
        raise ValueError(
            "radius_m must be between 100 and 50000 metres."
        )

    if not 1 <= limit <= 100:
        raise ValueError(
            "limit must be between 1 and 100."
        )

    api_key = _get_api_key()

    location = _geocode_destination(
        destination=destination,
        api_key=api_key,
    )

    if category == "attractions":
        provider_categories = ATTRACTION_CATEGORIES

    elif category == "restaurants":
        provider_categories = RESTAURANT_CATEGORIES

    else:
        provider_categories = (
            ATTRACTION_CATEGORIES + RESTAURANT_CATEGORIES
        )

    features = _fetch_places(
        api_key=api_key,
        lat=location["lat"],
        lon=location["lon"],
        radius_m=radius_m,
        categories=provider_categories,
        limit=limit,
    )

    places: List[Dict[str, Any]] = []
    seen_ids = set()

    for feature in features:
        place = _normalize_place(
            feature=feature,
            requested_category=category,
        )

        if not place:
            continue

        place_id = place["id"]

        if place_id in seen_ids:
            continue

        seen_ids.add(place_id)
        places.append(place)

    # Sort by distance if the API supplies it.
    places.sort(
        key=lambda item: (
            item["distance_m"]
            if isinstance(item["distance_m"], (int, float))
            else float("inf")
        )
    )

    return {
        "success": True,
        "destination": destination,
        "resolved_location": location["formatted"],
        "center": {
            "latitude": location["lat"],
            "longitude": location["lon"],
        },
        "radius_m": radius_m,
        "category": category,
        "count": len(places),
        "places": places,
        "data_notes": [
            "Place information is retrieved through Geoapify.",
            "Coverage and completeness vary by destination.",
            "Ratings and price levels are not provided by this implementation.",
            "Opening hours are included only when available.",
            "Missing opening hours do not mean a place is closed.",
            "Verify important travel details using a current reliable source.",
        ],
    }