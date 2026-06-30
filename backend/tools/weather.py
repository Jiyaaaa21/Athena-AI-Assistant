import requests

# Common city aliases — geocoding API knows official names
_CITY_ALIASES = {
    "gurgaon": "Gurugram",
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "bangalore": "Bengaluru",
    "poona": "Pune",
    "mysore": "Mysuru",
    "baroda": "Vadodara",
    "benaras": "Varanasi",
    "allahabad": "Prayagraj",
}


class WeatherTool:
    name = "weather"
    description = "Get current weather for a city"

    def run(self, city: str) -> str:
        if not city or city.strip().lower() in ("unknown", "none", ""):
            return "City not specified. Please provide a city name."

        # Resolve common aliases
        resolved = _CITY_ALIASES.get(city.strip().lower(), city.strip())

        try:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": resolved, "count": 1},
                timeout=8,
            )
            geo.raise_for_status()
            geo_data = geo.json()
        except Exception as e:
            return f"Could not look up '{resolved}': {e}"

        if "results" not in geo_data or not geo_data["results"]:
            return (
                f"City '{resolved}' not found in geocoding database. "
                f"Try the official city name (e.g. 'Gurugram' instead of 'Gurgaon')."
            )

        result = geo_data["results"][0]
        lat = result["latitude"]
        lon = result["longitude"]
        display_name = result.get("name", resolved)
        country = result.get("country", "")

        try:
            weather = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": (
                        "temperature_2m,apparent_temperature,"
                        "relative_humidity_2m,wind_speed_10m,"
                        "weather_code,precipitation"
                    ),
                    "timezone": "auto",
                },
                timeout=8,
            )
            weather.raise_for_status()
            data = weather.json()
        except Exception as e:
            return f"Weather fetch failed for '{display_name}': {e}"

        current = data.get("current", {})

        def wmo_description(code: int) -> str:
            WMO = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Foggy", 48: "Icy fog",
                51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                77: "Snow grains",
                80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
                85: "Slight snow showers", 86: "Heavy snow showers",
                95: "Thunderstorm", 96: "Thunderstorm with hail",
                99: "Thunderstorm with heavy hail",
            }
            return WMO.get(code, f"Weather code {code}")

        temp       = current.get("temperature_2m", "N/A")
        feels_like = current.get("apparent_temperature", "N/A")
        humidity   = current.get("relative_humidity_2m", "N/A")
        wind       = current.get("wind_speed_10m", "N/A")
        precip     = current.get("precipitation", 0)
        code       = current.get("weather_code", 0)
        condition  = wmo_description(int(code)) if code else "Unknown"

        return (
            f"City: {display_name}, {country}\n"
            f"Condition: {condition}\n"
            f"Temperature: {temp}°C\n"
            f"Feels Like: {feels_like}°C\n"
            f"Humidity: {humidity}%\n"
            f"Wind Speed: {wind} km/h\n"
            f"Precipitation: {precip} mm"
        )
