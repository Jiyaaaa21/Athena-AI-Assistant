import requests


class WeatherTool:

    name = "weather"

    description = (
        "Get current weather for a city"
    )

    def run(self, city):

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search"
        )

        geo_response = requests.get(
            geo_url,
            params={
                "name": city,
                "count": 1
            }
        )

        geo_data = geo_response.json()

        if "results" not in geo_data:

            return "City not found"

        latitude = geo_data["results"][0]["latitude"]
        longitude = geo_data["results"][0]["longitude"]

        weather_url = (
            "https://api.open-meteo.com/v1/forecast"
        )

        weather_response = requests.get(
            weather_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,"
                    "apparent_temperature,"
                    "relative_humidity_2m"
                )
            }
        )

        weather_data = weather_response.json()

        current = weather_data["current"]

        temperature = current["temperature_2m"]

        feels_like = current["apparent_temperature"]

        humidity = current["relative_humidity_2m"]

        return f"""
City: {city}

Temperature: {temperature}°C

Feels Like: {feels_like}°C

Humidity: {humidity}%
"""