from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException

router = APIRouter()

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Minimal WMO weather-code -> condition label mapping. Open-Meteo's docs
# define the full table; this covers the common buckets the UI needs.
WMO_CONDITIONS = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Cloudy",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def condition_for(code: int) -> str:
    return WMO_CONDITIONS.get(code, "Unknown")


def _geocode_candidates(city: str) -> list[str]:
    """
    Phase 4 fix: Open-Meteo's geocoder often can't resolve a full
    "City, State, Country" string (e.g. "Faridabad, Haryana, India" 404s
    even though "Faridabad" alone resolves fine). Build a list of
    progressively shorter candidates -- the full string first, then with
    trailing comma-separated parts dropped one at a time -- so a query
    typed naturally still finds a match.
    """

    parts = [p.strip() for p in city.split(",") if p.strip()]

    if not parts:
        return [city.strip()]

    candidates = []
    for i in range(len(parts), 0, -1):
        candidate = ", ".join(parts[:i])
        if candidate not in candidates:
            candidates.append(candidate)

    # Always also try just the first segment alone (the most common case:
    # someone typed "City, State, Country" and only the city resolves).
    if parts[0] not in candidates:
        candidates.append(parts[0])

    return candidates


def _geocode(city: str):
    """Tries each fallback candidate in turn, returns the first match's
    place dict, or None if nothing resolved."""

    for candidate in _geocode_candidates(city):

        geo_response = requests.get(
            GEOCODE_URL,
            params={"name": candidate, "count": 1},
            timeout=10,
        )
        geo_data = geo_response.json()

        if "results" in geo_data and geo_data["results"]:
            return geo_data["results"][0]

    return None


@router.get("/weather")
def get_weather(city: str):

    if not city or not city.strip():
        raise HTTPException(status_code=400, detail="City is required")

    place = _geocode(city)

    if not place:
        raise HTTPException(status_code=404, detail=f"City not found: {city}")

    latitude = place["latitude"]
    longitude = place["longitude"]
    resolved_name = place.get("name", city)

    weather_response = requests.get(
        FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 5,
            "timezone": "auto",
        },
        timeout=10,
    )
    weather_data = weather_response.json()

    current = weather_data.get("current", {})
    daily = weather_data.get("daily", {})

    forecast = []
    days = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])

    for i, day_str in enumerate(days):
        date_obj = datetime.fromisoformat(day_str)
        forecast.append({
            "day": date_obj.strftime("%a"),
            "hi": round(highs[i]) if i < len(highs) else None,
            "lo": round(lows[i]) if i < len(lows) else None,
            "condition": condition_for(codes[i]) if i < len(codes) else "Unknown",
        })

    current_code = current.get("weather_code", 0)

    return {
        "city": resolved_name,
        "temperatureC": round(current.get("temperature_2m", 0)),
        "feelsLikeC": round(current.get("apparent_temperature", 0)),
        "humidity": round(current.get("relative_humidity_2m", 0)),
        "condition": condition_for(current_code),
        "icon": condition_for(current_code).lower().replace(" ", "-"),
        "forecast": forecast,
    }