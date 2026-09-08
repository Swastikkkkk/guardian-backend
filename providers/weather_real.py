"""
Real, free, no-API-key weather via Open-Meteo (https://open-meteo.com).
Replaces the DEMO weather placeholder with genuine current-conditions
data. Falls back to a neutral ESTIMATED value (never fabricated REAL
data) if the service is unreachable.
"""
from __future__ import annotations
from datetime import datetime

import requests

from models.enums import DataLabel
from models.schemas import LatLng, Sourced
from providers.base import WeatherDataProvider

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_REQUEST_TIMEOUT_S = 6


class OpenMeteoWeatherDataProvider(WeatherDataProvider):
    def get_weather_score(self, point: LatLng, at_time: datetime) -> Sourced:
        try:
            resp = requests.get(
                OPEN_METEO_URL,
                params={
                    "latitude": point.lat, "longitude": point.lng,
                    "current": "precipitation,weather_code,wind_speed_10m",
                },
                timeout=_REQUEST_TIMEOUT_S,
            )
            resp.raise_for_status()
            current = resp.json().get("current", {})
        except Exception:
            return Sourced(value=0.8, label=DataLabel.ESTIMATED, source_name="Open-Meteo (unreachable)")

        precipitation = current.get("precipitation") or 0.0
        wind_speed = current.get("wind_speed_10m") or 0.0

        score = 1.0
        if precipitation > 0:
            score -= min(0.5, precipitation * 0.15)  # heavier rain -> more visibility/mobility impact
        if wind_speed > 30:  # km/h
            score -= 0.2

        return Sourced(value=round(max(0.1, score), 3), label=DataLabel.REAL, source_name="Open-Meteo")
