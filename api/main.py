"""
Guardian Geospatial Intelligence API.

Clean JSON endpoints the SwiftUI iPhone app consumes. This process owns
no UI and no hardware integration - it is purely the intelligence/data
backend described in the module brief.

Run: uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models.enums import RiskLevel, DataLabel
from models.schemas import (
    LatLng, SafeRouteRequest, SafeRouteResult, AreaSafetyRequest, SafetyEvent,
    CCTVEvent, GeoJSONFeatureCollection, new_id, ScoreGeometryRequest, RouteCandidate,
)
from providers.registry import DEFAULT_REGISTRY
from routes.safe_route_engine import ENGINE
from scoring.segment_scoring import score_segment
from scoring.route_scoring import score_route
from data.event_bus import EVENT_BUS
from geospatial.geojson_utils import (
    feature_collection, poi_to_feature, crime_record_to_feature,
    safety_event_to_feature, cctv_event_to_feature, route_segment_to_feature,
)
from geospatial.utils import split_into_segments, polyline_length_m
from cv.event_translator import cctv_event_to_safety_event

app = FastAPI(
    title="Guardian Geospatial Intelligence & Safe Route Optimization",
    version="1.0.0",
    description="Intelligence/data backend for the Guardian women's safety platform. "
                "Consumes geospatial/historical/environmental/real-time/CV signals and "
                "exposes structured safety data + safe routing for the iPhone app.",
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@app.post("/route/safe", response_model=SafeRouteResult, tags=["routes"])
def post_safe_route(req: SafeRouteRequest):
    """Core endpoint: given origin/destination(/current location/time),
    returns the recommended safest-practical route plus scored alternatives."""
    at_time = req.departure_time or _now()
    result = ENGINE.plan(req.origin, req.destination, at_time=at_time, max_alternatives=req.max_alternatives)
    return result


@app.post("/route/score-geometry", tags=["routes"])
def post_score_geometry(req: ScoreGeometryRequest):
    """Score a real route polyline from an external routing engine (OSRM,
    Google Directions, Mapbox, etc). Use this when you already have real
    road-following geometry and just want Guardian's safety scoring
    layered on top, instead of Guardian's own synthetic candidate routes."""
    if len(req.geometry) < 2:
        raise HTTPException(400, "geometry must contain at least 2 points")
    at_time = req.at_time or _now()
    distance = polyline_length_m(req.geometry)
    duration = req.estimated_duration_s or (distance / 1.35)
    candidate = RouteCandidate(
        geometry=req.geometry, distance_m=round(distance, 1),
        estimated_duration_s=round(duration, 1), provider=req.provider,
    )
    scored = score_route(candidate, at_time, DEFAULT_REGISTRY)
    ENGINE._route_cache[scored.id] = scored
    return scored


@app.get("/route/{route_id}", tags=["routes"])
def get_route(route_id: str):
    route = ENGINE.get_route(route_id)
    if route is None:
        raise HTTPException(404, f"Route {route_id} not found (routes are cached per-process; re-run /route/safe)")
    return route


@app.get("/route/{route_id}/segments", tags=["routes"])
def get_route_segments(route_id: str, as_geojson: bool = Query(False)):
    route = ENGINE.get_route(route_id)
    if route is None:
        raise HTTPException(404, f"Route {route_id} not found")
    if as_geojson:
        return feature_collection(route_segment_to_feature(s) for s in route.segments)
    return route.segments


@app.post("/route/{route_id}/check-reroute", tags=["routes"])
def check_dynamic_reroute(
    route_id: str,
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
):
    """Call periodically (or on push from the live pipeline) while a user
    is mid-journey to see if a materially safer alternative has emerged."""
    update = ENGINE.dynamic_reroute(
        route_id,
        LatLng(lat=origin_lat, lng=origin_lng),
        LatLng(lat=dest_lat, lng=dest_lng),
    )
    if update is None:
        return {"reroute_available": False}
    return {"reroute_available": True, "update": update}


# ---------------------------------------------------------------------------
# Area / point safety
# ---------------------------------------------------------------------------

@app.get("/safety/area", tags=["safety"])
def get_area_safety(lat: float, lng: float, radius_m: float = 500.0, at_time: Optional[datetime] = None):
    """Scores a single representative segment centered on the point - a
    lightweight way to render an area's safety without a full route."""
    at_time = at_time or _now()
    point = LatLng(lat=lat, lng=lng)
    # build a tiny synthetic 2-point "segment" at the point so we can reuse
    # the exact same scoring code path used for real route segments.
    geometry = [point, LatLng(lat=lat + 0.0009, lng=lng + 0.0009)]  # ~100m
    segment = score_segment(0, geometry, at_time, DEFAULT_REGISTRY)
    return {
        "center": point,
        "radius_m": radius_m,
        "safety_score": segment.overall_safety_score,
        "risk_level": segment.risk_level,
        "confidence": segment.confidence,
        "positive_factors": segment.positive_factors,
        "negative_factors": segment.negative_factors,
        "breakdown": segment.scores,
    }


@app.get("/safety/nearby", tags=["safety"])
def get_safety_nearby(lat: float, lng: float, radius_m: float = 500.0):
    """Everything known near a point: incidents, CCTV events, POIs -
    useful for a map overlay."""
    point = LatLng(lat=lat, lng=lng)
    now = _now()
    incidents = EVENT_BUS.query_near(point, radius_m, now=now)
    cctv_events = EVENT_BUS.query_cctv_near(point, radius_m)
    police = DEFAULT_REGISTRY.emergency_infra.get_police_near(point, radius_m)
    hospitals = DEFAULT_REGISTRY.emergency_infra.get_hospitals_near(point, radius_m)
    safe_places = DEFAULT_REGISTRY.safe_places.get_safe_places_near(point, radius_m)
    cameras = DEFAULT_REGISTRY.cctv.get_cameras_near(point, radius_m)
    return {
        "center": point,
        "incidents": incidents,
        "cctv_events": cctv_events,
        "police_stations": police,
        "hospitals": hospitals,
        "safe_places": safe_places,
        "cctv_cameras": cameras,
    }


# ---------------------------------------------------------------------------
# Incidents / CCTV / safe places / environment (raw layer endpoints)
# ---------------------------------------------------------------------------

@app.get("/incidents", tags=["data layers"])
def get_incidents(lat: float, lng: float, radius_m: float = 1000.0, as_geojson: bool = Query(False)):
    point = LatLng(lat=lat, lng=lng)
    incidents = EVENT_BUS.query_near(point, radius_m)
    if as_geojson:
        return feature_collection(safety_event_to_feature(e) for e in incidents)
    return incidents


@app.get("/cctv/events", tags=["data layers"])
def get_cctv_events(lat: float, lng: float, radius_m: float = 1000.0, as_geojson: bool = Query(False)):
    point = LatLng(lat=lat, lng=lng)
    events = EVENT_BUS.query_cctv_near(point, radius_m)
    if as_geojson:
        return feature_collection(cctv_event_to_feature(e) for e in events)
    return events


@app.get("/safe-places", tags=["data layers"])
def get_safe_places(lat: float, lng: float, radius_m: float = 1000.0, as_geojson: bool = Query(False)):
    point = LatLng(lat=lat, lng=lng)
    places = DEFAULT_REGISTRY.safe_places.get_safe_places_near(point, radius_m)
    if as_geojson:
        return feature_collection(poi_to_feature(p) for p in places)
    return places


@app.get("/environment", tags=["data layers"])
def get_environment(lat: float, lng: float, at_time: Optional[datetime] = None):
    at_time = at_time or _now()
    point = LatLng(lat=lat, lng=lng)
    weather = DEFAULT_REGISTRY.weather.get_weather_score(point, at_time)
    satellite = DEFAULT_REGISTRY.satellite.get_environmental_context(point)
    connectivity = DEFAULT_REGISTRY.connectivity.get_connectivity_score(point)
    return {"weather": weather, "satellite_context": satellite, "connectivity": connectivity}


# ---------------------------------------------------------------------------
# Ingesting live/CV events
# ---------------------------------------------------------------------------

@app.post("/events", tags=["ingestion"])
def post_event(event: SafetyEvent):
    """Generic live-event ingestion (incidents, weather, traffic, transport,
    crowd, connectivity, environmental). Normalizes and stores with TTL."""
    published = EVENT_BUS.publish(event)
    return {"stored": True, "event": published}


@app.post("/events/cctv", tags=["ingestion"])
def post_cctv_event(event: CCTVEvent):
    """Ingest a CV-model-generated CCTVEvent. Automatically fanned out into
    the unified SafetyEvent pipeline so it affects scoring immediately."""
    stored = EVENT_BUS.publish_cctv_event(event)
    safety_event = cctv_event_to_safety_event(stored)
    EVENT_BUS.publish(safety_event)
    return {"stored": True, "event": stored, "derived_safety_event_id": safety_event.id}


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "Guardian Geospatial Intelligence & Safe Route Optimization",
        "status": "ok",
        "mode": "demo (all providers labeled SIMULATED/ESTIMATED unless real APIs configured)",
        "docs": "/docs",
    }
