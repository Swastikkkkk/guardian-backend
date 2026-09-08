"""
Real, free, crowdsourced OpenStreetMap-backed providers, via the public
Overpass API (https://overpass-api.de) - no API key required.

This replaces the DEMO placeholders for road classification, street
lighting, CCTV camera presence, police/hospital/emergency proximity,
safe places, and public transport stops with genuine, community-mapped
data, labeled DataLabel.REAL.

Important honesty note: OSM coverage varies enormously by region. A
point with sparse local mapping will legitimately return "nothing found"
- that is a true negative, not a failure, and callers must NOT quietly
fall back to fabricated data to fill the gap. When Overpass is
unreachable (network/timeout), these providers return DataLabel.ESTIMATED
neutral values instead of pretending REAL data was available.
"""
from __future__ import annotations
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from models.enums import DataLabel, RoadType
from models.schemas import LatLng, PointOfInterest, Sourced
from providers.base import (
    RoadDataProvider, LightingDataProvider, CCTVDataProvider,
    EmergencyInfrastructureProvider, SafePlaceDataProvider, PublicTransportProvider,
    FootfallDataProvider,
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_REQUEST_TIMEOUT_S = 4
_FAILURE_CACHE_TTL_S = 30  # short-circuit repeat calls after a failure so one unreachable window doesn't multiply into minutes of stalled requests
_CACHE_TTL_S = 300  # avoid hammering the free public Overpass instance
_CACHE: Dict[str, Any] = {}

_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))

# Circuit breaker: a single route can trigger a dozen distinct Overpass
# queries per segment (road, lighting, cctv, police, hospital, clinic,
# fire_station, 3x safe-place amenities, transport, activity), each with
# its own cache key. If Overpass is unreachable from this network, every
# one of those still pays its own timeout on first use - which, summed
# across a multi-segment route, stalls the whole request for minutes even
# though _CACHE now remembers each individual failure. Once ANY call
# fails, assume Overpass is down for everyone for a cooldown window and
# skip the network entirely instead of re-discovering that N more times.
_BREAKER_COOLDOWN_S = 60
_breaker_tripped_at: Optional[float] = None


def _breaker_is_open() -> bool:
    return _breaker_tripped_at is not None and time.time() - _breaker_tripped_at < _BREAKER_COOLDOWN_S


def _cache_key(tag: str, point: LatLng, radius_m: float) -> str:
    return f"{tag}:{round(point.lat, 3)}:{round(point.lng, 3)}:{int(radius_m)}"


def _overpass_query(query: str, cache_key: str) -> Optional[dict]:
    global _breaker_tripped_at
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached is not None:
        cached_at, cached_data = cached
        ttl = _CACHE_TTL_S if cached_data is not None else _FAILURE_CACHE_TTL_S
        if now - cached_at < ttl:
            return cached_data
    if _breaker_is_open():
        return None  # Overpass already known-unreachable this window - fail fast, no network attempt
    try:
        resp = _session.post(OVERPASS_URL, data={"data": query}, timeout=_REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        _CACHE[cache_key] = (now, data)
        # Deliberately NOT clearing _breaker_tripped_at here: Overpass has
        # proven flaky (intermittent success mixed with timeouts) rather
        # than cleanly up or down, and clearing on every lucky success let
        # the breaker flap open/closed within a single route request -
        # each subsequent segment paying its own ~8s rediscovery cost
        # instead of staying fast for the rest of the cooldown window. Let
        # it expire naturally via _BREAKER_COOLDOWN_S instead.
        return data
    except Exception:
        _CACHE[cache_key] = (now, None)  # cache the failure too, so a whole route's worth of segments don't each re-pay the full timeout
        _breaker_tripped_at = now
        return None  # network/timeout - caller must treat this as "no data available", not zero risk


HIGHWAY_TO_ROADTYPE = {
    "motorway": RoadType.HIGHWAY, "trunk": RoadType.HIGHWAY,
    "primary": RoadType.MAIN, "secondary": RoadType.MAIN, "tertiary": RoadType.MAIN,
    "residential": RoadType.RESIDENTIAL, "living_street": RoadType.RESIDENTIAL,
    "unclassified": RoadType.RESIDENTIAL,
    "pedestrian": RoadType.PEDESTRIAN, "footway": RoadType.PEDESTRIAN, "path": RoadType.PEDESTRIAN,
    "track": RoadType.UNPAVED,
}


class OSMRoadDataProvider(RoadDataProvider):
    def classify_road(self, point: LatLng) -> Sourced:
        radius = 40
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        way(around:{radius},{point.lat},{point.lng})["highway"];
        out tags 1;
        """
        data = _overpass_query(query, _cache_key("road", point, radius))
        if data is None:
            return Sourced(value=RoadType.UNKNOWN, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (unreachable)")
        elements = data.get("elements", [])
        if not elements:
            return Sourced(value=RoadType.UNKNOWN, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (no road tagged nearby)")
        tags = elements[0].get("tags", {})
        road_type = HIGHWAY_TO_ROADTYPE.get(tags.get("highway", ""), RoadType.UNKNOWN)
        if tags.get("surface") in ("unpaved", "dirt", "gravel", "ground"):
            road_type = RoadType.UNPAVED
        return Sourced(value=road_type, label=DataLabel.REAL, source_name="OpenStreetMap")

    def get_road_condition(self, point: LatLng) -> Sourced:
        radius = 40
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        way(around:{radius},{point.lat},{point.lng})["highway"];
        out tags 1;
        """
        data = _overpass_query(query, _cache_key("road", point, radius))
        if data is None:
            return Sourced(value=0.6, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (unreachable)")
        elements = data.get("elements", [])
        if not elements:
            return Sourced(value=0.6, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (no road tagged nearby)")
        surface = elements[0].get("tags", {}).get("surface", "")
        good = {"paved", "asphalt", "concrete"}
        bad = {"unpaved", "dirt", "gravel", "ground", "grass", "mud"}
        if surface in good:
            return Sourced(value=0.85, label=DataLabel.REAL, source_name="OpenStreetMap")
        if surface in bad:
            return Sourced(value=0.35, label=DataLabel.REAL, source_name="OpenStreetMap")
        return Sourced(value=0.6, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (surface not tagged)")


class OSMLightingDataProvider(LightingDataProvider):
    def get_lighting_score(self, point: LatLng, at_time: datetime) -> Sourced:
        radius = 60
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        (
          way(around:{radius},{point.lat},{point.lng})["lit"];
          node(around:{radius},{point.lat},{point.lng})["highway"="street_lamp"];
        );
        out tags 30;
        """
        data = _overpass_query(query, _cache_key("lit", point, radius))
        if data is None:
            return Sourced(value=0.5, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (unreachable)")
        elements = data.get("elements", [])
        if not elements:
            return Sourced(value=0.5, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (no lighting data mapped nearby)")

        lamp_count = sum(1 for e in elements if e.get("tags", {}).get("highway") == "street_lamp")
        lit_yes = sum(1 for e in elements if e.get("tags", {}).get("lit") == "yes")
        lit_no = sum(1 for e in elements if e.get("tags", {}).get("lit") == "no")

        score = 0.5 + 0.1 * min(lamp_count, 3) + 0.15 * min(lit_yes, 2) - 0.3 * min(lit_no, 2)
        score = max(0.1, min(1.0, score))
        is_dark = at_time.hour >= 19 or at_time.hour < 6
        if not is_dark:
            score = min(1.0, score + 0.15)  # lighting infrastructure matters most after dark
        return Sourced(value=round(score, 3), label=DataLabel.REAL, source_name="OpenStreetMap")


class OSMCCTVDataProvider(CCTVDataProvider):
    def get_cameras_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        node(around:{radius_m},{point.lat},{point.lng})["man_made"="surveillance"];
        out tags 50;
        """
        data = _overpass_query(query, _cache_key("cctv", point, radius_m))
        if not data:
            return []
        return [
            PointOfInterest(
                type="cctv_camera", name=el.get("tags", {}).get("name", "CCTV camera"),
                latitude=el["lat"], longitude=el["lon"], label=DataLabel.REAL,
            )
            for el in data.get("elements", []) if "lat" in el and "lon" in el
        ]

    def get_recent_events_near(self, point: LatLng, radius_m: float, since: datetime) -> List:
        # OSM has no live event feed. Real-time anomalies still flow
        # through data/event_bus.py (CV models / manual injection), which
        # segment_scoring.py already queries independently of this provider.
        return []


class OSMEmergencyInfrastructureProvider(EmergencyInfrastructureProvider):
    def _query_amenity(self, point: LatLng, radius_m: float, amenity: str, poi_type: str) -> List[PointOfInterest]:
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        node(around:{radius_m},{point.lat},{point.lng})["amenity"="{amenity}"];
        out tags 50;
        """
        data = _overpass_query(query, _cache_key(amenity, point, radius_m))
        if not data:
            return []
        return [
            PointOfInterest(
                type=poi_type, name=el.get("tags", {}).get("name", amenity.replace("_", " ").title()),
                latitude=el["lat"], longitude=el["lon"], label=DataLabel.REAL,
            )
            for el in data.get("elements", []) if "lat" in el and "lon" in el
        ]

    def get_police_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        return self._query_amenity(point, radius_m, "police", "police")

    def get_hospitals_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        return (self._query_amenity(point, radius_m, "hospital", "hospital")
                + self._query_amenity(point, radius_m, "clinic", "hospital"))

    def get_emergency_services_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        return self._query_amenity(point, radius_m, "fire_station", "emergency")


class OSMSafePlaceDataProvider(SafePlaceDataProvider):
    _AMENITIES = ["pharmacy", "fuel", "community_centre"]

    def get_safe_places_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        results: List[PointOfInterest] = []
        for amenity in self._AMENITIES:
            query = f"""
            [out:json][timeout:{_REQUEST_TIMEOUT_S}];
            node(around:{radius_m},{point.lat},{point.lng})["amenity"="{amenity}"];
            out tags 20;
            """
            data = _overpass_query(query, _cache_key(f"safe_{amenity}", point, radius_m))
            if not data:
                continue
            for el in data.get("elements", []):
                if "lat" not in el or "lon" not in el:
                    continue
                results.append(PointOfInterest(
                    type="safe_place", name=el.get("tags", {}).get("name", amenity.replace("_", " ").title()),
                    latitude=el["lat"], longitude=el["lon"], label=DataLabel.REAL,
                ))
        return results


class OSMPublicTransportProvider(PublicTransportProvider):
    def get_stops_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        node(around:{radius_m},{point.lat},{point.lng})["highway"="bus_stop"];
        out tags 30;
        """
        data = _overpass_query(query, _cache_key("transport", point, radius_m))
        if not data:
            return []
        return [
            PointOfInterest(
                type="transport", name=el.get("tags", {}).get("name", "Bus stop"),
                latitude=el["lat"], longitude=el["lon"], label=DataLabel.REAL,
            )
            for el in data.get("elements", []) if "lat" in el and "lon" in el
        ]


class OSMActivityDensityProvider(FootfallDataProvider):
    """Honest replacement for the simulated 'footfall score'.

    There is no free, live, publicly-available API anywhere that counts
    real-time pedestrian foot traffic - Google's "Popular Times" data is
    not exposed through any official API, and real crowd-counting
    requires either paid mobility-data contracts or physical sensors.

    Rather than fabricate a number, this counts REAL, actually-mapped
    points of interest (shops, cafes, restaurants, mixed amenities) from
    OpenStreetMap near a point, as a genuine (if imperfect and NOT
    real-time) proxy for how much everyday activity a place tends to
    have. Every number this returns traces to an actual mapped location -
    zero random generation. It is explicitly NOT a live headcount, and
    the API always labels it REAL (a genuine OSM count) rather than
    pretending it is a live sensor reading.
    """
    _ACTIVITY_TAGS = [
        ("shop", None),           # any shop=* value
        ("amenity", "cafe"),
        ("amenity", "restaurant"),
        ("amenity", "marketplace"),
        ("amenity", "bar"),
    ]
    _SATURATION_COUNT = 15  # this many real mapped venues nearby = "as busy as it gets" for scoring purposes

    def get_activity_score(self, point: LatLng, at_time: datetime) -> Sourced:
        radius = 150
        clauses = []
        for key, value in self._ACTIVITY_TAGS:
            if value:
                clauses.append(f'node(around:{radius},{point.lat},{point.lng})["{key}"="{value}"];')
            else:
                clauses.append(f'node(around:{radius},{point.lat},{point.lng})["{key}"];')
        query = f"""
        [out:json][timeout:{_REQUEST_TIMEOUT_S}];
        (
          {' '.join(clauses)}
        );
        out count;
        """
        data = _overpass_query(query, _cache_key("activity", point, radius))
        if data is None:
            return Sourced(value=0.5, label=DataLabel.ESTIMATED, source_name="OpenStreetMap (unreachable)")

        # Overpass "out count" returns one element with a tags.total field.
        elements = data.get("elements", [])
        total = 0
        if elements and "tags" in elements[0]:
            total = int(elements[0]["tags"].get("total", 0))

        real_venue_count = total
        score = min(1.0, real_venue_count / self._SATURATION_COUNT)
        return Sourced(
            value=round(score, 3), label=DataLabel.REAL, source_name="OpenStreetMap",
            freshness_seconds=None, raw_count=real_venue_count,
        )
