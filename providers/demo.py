"""
DemoDataProvider implementations.

These generate deterministic, realistic-looking synthetic data (seeded by
location so repeated queries near the same point are stable) for every
provider interface. All values are labeled SIMULATED. This lets the whole
Guardian pipeline run end-to-end with zero external API keys, and each
class can be swapped for a REAL implementation later without touching
scoring/route code, since callers only depend on providers/base.py.
"""
from __future__ import annotations
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from models.enums import RoadType, DataLabel, CVEventType, SafetyEventSource, SafetyEventSeverity
from models.schemas import (
    LatLng, CrimeRecord, PointOfInterest, SafetyEvent, CCTVEvent, Sourced, new_id,
)
from geospatial.utils import haversine_m
from providers.base import (
    CrimeDataProvider, LightingDataProvider, RoadDataProvider, FootfallDataProvider,
    CCTVDataProvider, IncidentDataProvider, WeatherDataProvider, ConnectivityDataProvider,
    SatelliteDataProvider, SafePlaceDataProvider, EmergencyInfrastructureProvider,
    PublicTransportProvider, BusinessDataProvider,
)


def _seeded_rng(*parts) -> random.Random:
    """Deterministic RNG keyed off rounded coordinates (and any extra parts)
    so repeated calls near the same location return stable synthetic data."""
    key = "|".join(str(p) for p in parts)
    h = hashlib.sha256(key.encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _grid_key(point: LatLng, precision: int = 3) -> str:
    return f"{round(point.lat, precision)}:{round(point.lng, precision)}"


class DemoCrimeDataProvider(CrimeDataProvider):
    def get_records_near(self, point: LatLng, radius_m: float, since: Optional[datetime] = None) -> List[CrimeRecord]:
        rng = _seeded_rng(_grid_key(point), "crime")
        count = rng.randint(0, 6)
        now = datetime.now(timezone.utc)
        categories = ["theft", "harassment", "assault", "robbery", "eve_teasing", "stalking"]
        records = []
        for _ in range(count):
            offset_lat = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            offset_lng = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            days_ago = rng.uniform(1, 730)
            ts = now - timedelta(days=days_ago)
            if since and ts < since:
                continue
            records.append(CrimeRecord(
                latitude=point.lat + offset_lat,
                longitude=point.lng + offset_lng,
                category=rng.choice(categories),
                severity=round(rng.uniform(0.2, 1.0), 2),
                timestamp=ts,
                label=DataLabel.SIMULATED,
            ))
        return records


class DemoLightingDataProvider(LightingDataProvider):
    def get_lighting_score(self, point: LatLng, at_time: datetime) -> Sourced:
        rng = _seeded_rng(_grid_key(point), "lighting")
        base = rng.uniform(0.3, 0.95)
        hour = at_time.hour
        # Lighting infrastructure matters most when it's dark.
        is_dark = hour >= 19 or hour < 6
        score = base if is_dark else min(1.0, base + 0.15)
        return Sourced(value=round(score, 3), label=DataLabel.SIMULATED, source_name="DemoLightingDataProvider")


class DemoRoadDataProvider(RoadDataProvider):
    _TYPES = [RoadType.MAIN, RoadType.RESIDENTIAL, RoadType.PEDESTRIAN,
              RoadType.HIGHWAY, RoadType.ISOLATED, RoadType.UNPAVED]

    def classify_road(self, point: LatLng) -> Sourced:
        rng = _seeded_rng(_grid_key(point, 4), "road_type")
        weights = [0.30, 0.30, 0.12, 0.08, 0.12, 0.08]
        road = rng.choices(self._TYPES, weights=weights, k=1)[0]
        return Sourced(value=road, label=DataLabel.SIMULATED, source_name="DemoRoadDataProvider")

    def get_road_condition(self, point: LatLng) -> Sourced:
        rng = _seeded_rng(_grid_key(point, 4), "road_condition")
        return Sourced(value=round(rng.uniform(0.4, 1.0), 3), label=DataLabel.SIMULATED,
                        source_name="DemoRoadDataProvider")


class DemoFootfallDataProvider(FootfallDataProvider):
    def get_activity_score(self, point: LatLng, at_time: datetime) -> Sourced:
        rng = _seeded_rng(_grid_key(point), "footfall")
        base = rng.uniform(0.2, 0.9)
        hour = at_time.hour
        # crude diurnal curve: activity peaks midday/evening, drops late night
        curve = {
            range(0, 6): 0.3, range(6, 11): 0.8, range(11, 16): 1.0,
            range(16, 20): 0.95, range(20, 23): 0.6, range(23, 24): 0.25,
        }
        mult = 0.5
        for r, m in curve.items():
            if hour in r:
                mult = m
                break
        return Sourced(value=round(min(1.0, base * mult + 0.05), 3), label=DataLabel.SIMULATED,
                        source_name="DemoFootfallDataProvider")


class DemoCCTVDataProvider(CCTVDataProvider):
    def get_cameras_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        rng = _seeded_rng(_grid_key(point), "cctv_cameras")
        count = rng.randint(0, 5)
        cams = []
        for i in range(count):
            offset_lat = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            offset_lng = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            cams.append(PointOfInterest(
                type="cctv_camera", name=f"CCTV-{i}",
                latitude=point.lat + offset_lat, longitude=point.lng + offset_lng,
                label=DataLabel.SIMULATED,
            ))
        return cams

    def get_recent_events_near(self, point: LatLng, radius_m: float, since: datetime) -> List[CCTVEvent]:
        # Demo mode ships with zero *ambient* events; use simulation/event_generator
        # or POST /events to inject events for a demo. Keeps baseline scoring stable.
        return []


class DemoIncidentDataProvider(IncidentDataProvider):
    def get_recent_incidents_near(self, point: LatLng, radius_m: float, since: datetime) -> List[SafetyEvent]:
        return []  # live incidents come from the event bus (simulation/live_events); none by default


class DemoWeatherDataProvider(WeatherDataProvider):
    def get_weather_score(self, point: LatLng, at_time: datetime) -> Sourced:
        rng = _seeded_rng(_grid_key(point, 1), "weather", at_time.strftime("%Y-%m-%d"))
        return Sourced(value=round(rng.uniform(0.6, 1.0), 3), label=DataLabel.SIMULATED,
                        source_name="DemoWeatherDataProvider")


class DemoConnectivityDataProvider(ConnectivityDataProvider):
    def get_connectivity_score(self, point: LatLng) -> Sourced:
        rng = _seeded_rng(_grid_key(point), "connectivity")
        return Sourced(value=round(rng.uniform(0.4, 1.0), 3), label=DataLabel.SIMULATED,
                        source_name="DemoConnectivityDataProvider")


class DemoSatelliteDataProvider(SatelliteDataProvider):
    def get_environmental_context(self, point: LatLng) -> Sourced:
        rng = _seeded_rng(_grid_key(point, 2), "satellite")
        ctx = {
            "land_use": rng.choice(["urban", "suburban", "commercial", "open_land", "vegetated"]),
            "vegetation_density": round(rng.uniform(0.0, 0.8), 2),
            "flood_risk": round(rng.uniform(0.0, 0.3), 2),
            "terrain_isolation": round(rng.uniform(0.0, 0.6), 2),
        }
        return Sourced(
            value=ctx, label=DataLabel.SIMULATED, source_name="DemoSatelliteDataProvider",
            freshness_seconds=None,
        )


class DemoSafePlaceDataProvider(SafePlaceDataProvider):
    def get_safe_places_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        rng = _seeded_rng(_grid_key(point), "safe_places")
        count = rng.randint(0, 4)
        names = ["24hr Pharmacy", "Petrol Pump", "Community Center", "Metro Station Help Desk", "Women's Help Booth"]
        places = []
        for i in range(count):
            offset_lat = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            offset_lng = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            places.append(PointOfInterest(
                type="safe_place", name=rng.choice(names),
                latitude=point.lat + offset_lat, longitude=point.lng + offset_lng,
                label=DataLabel.SIMULATED,
            ))
        return places


class DemoEmergencyInfrastructureProvider(EmergencyInfrastructureProvider):
    def _generate(self, point: LatLng, radius_m: float, kind: str, salt: str, name_prefix: str, max_count: int) -> List[PointOfInterest]:
        rng = _seeded_rng(_grid_key(point, 2), salt)
        count = rng.randint(0, max_count)
        items = []
        for i in range(count):
            offset_lat = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            offset_lng = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            items.append(PointOfInterest(
                type=kind, name=f"{name_prefix} {i+1}",
                latitude=point.lat + offset_lat, longitude=point.lng + offset_lng,
                label=DataLabel.SIMULATED,
            ))
        return items

    def get_police_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        return self._generate(point, radius_m, "police", "police", "Police Station", 2)

    def get_hospitals_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        return self._generate(point, radius_m, "hospital", "hospital", "Hospital", 3)

    def get_emergency_services_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        return self._generate(point, radius_m, "emergency", "emergency", "Emergency Service Point", 2)


class DemoPublicTransportProvider(PublicTransportProvider):
    def get_stops_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        rng = _seeded_rng(_grid_key(point), "transport")
        count = rng.randint(0, 4)
        stops = []
        for i in range(count):
            offset_lat = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            offset_lng = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            stops.append(PointOfInterest(
                type="transport", name=f"Transit Stop {i+1}",
                latitude=point.lat + offset_lat, longitude=point.lng + offset_lng,
                label=DataLabel.SIMULATED,
            ))
        return stops


class DemoBusinessDataProvider(BusinessDataProvider):
    def get_open_businesses_near(self, point: LatLng, radius_m: float, at_time: datetime) -> List[PointOfInterest]:
        rng = _seeded_rng(_grid_key(point), "business")
        count = rng.randint(0, 6)
        open_hour, close_hour = 8, 22
        is_open_hours = open_hour <= at_time.hour < close_hour
        businesses = []
        for i in range(count):
            offset_lat = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            offset_lng = rng.uniform(-1, 1) * (radius_m / 111_320.0)
            businesses.append(PointOfInterest(
                type="business", name=f"Local Business {i+1}",
                latitude=point.lat + offset_lat, longitude=point.lng + offset_lng,
                label=DataLabel.SIMULATED, open_now=is_open_hours and rng.random() > 0.2,
            ))
        return businesses
