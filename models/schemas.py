"""
Pydantic data contracts shared across the whole module.

These are the exact JSON shapes the iPhone app will see, so field names
here are the API contract - change them deliberately and bump the API
version if you do.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from models.enums import (
    DataLabel, RoadType, RiskLevel, CVEventType, SafetyEventSource, SafetyEventSeverity,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Geometry / GeoJSON
# ---------------------------------------------------------------------------

class LatLng(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)

    def as_geojson_coord(self) -> List[float]:
        return [self.lng, self.lat]  # GeoJSON is [lng, lat]


class GeoJSONGeometry(BaseModel):
    type: Literal["Point", "LineString", "Polygon"]
    coordinates: Any


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry
    properties: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[GeoJSONFeature] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sourced values - every datum carries provenance
# ---------------------------------------------------------------------------

class Sourced(BaseModel):
    """Wraps a value with provenance so nothing is presented as ground
    truth when it is really SIMULATED / CACHED / ESTIMATED."""
    value: Any
    label: DataLabel
    source_name: str
    as_of: datetime = Field(default_factory=utcnow)
    freshness_seconds: Optional[float] = None
    raw_count: Optional[int] = None  # the actual underlying real count, when the value is a normalized score derived from one (e.g. real OSM venues found nearby) - lets callers show a genuine number instead of just a 0..1 score


# ---------------------------------------------------------------------------
# CCTV / Computer Vision
# ---------------------------------------------------------------------------

class CCTVEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cctv_"))
    camera_id: str
    latitude: float
    longitude: float
    timestamp: datetime = Field(default_factory=utcnow)
    event_type: CVEventType
    confidence: float = Field(..., ge=0.0, le=1.0)
    severity: SafetyEventSeverity
    label: DataLabel = DataLabel.SIMULATED
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def no_identity_claims(cls, v):
        # Guardrail: never let free text assert a criminal identity.
        banned = ["criminal", "suspect is a", "thief is", "attacker is"]
        if v:
            low = v.lower()
            for b in banned:
                if b in low:
                    raise ValueError("CCTV descriptions must not assert identity/criminality")
        return v


# ---------------------------------------------------------------------------
# Live safety events (unified envelope for anything real-time)
# ---------------------------------------------------------------------------

class SafetyEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt_"))
    timestamp: datetime = Field(default_factory=utcnow)
    location: LatLng
    source: SafetyEventSource
    type: str
    severity: SafetyEventSeverity
    confidence: float = Field(..., ge=0.0, le=1.0)
    expires_at: Optional[datetime] = None
    label: DataLabel = DataLabel.SIMULATED
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def ensure_expiry(self, default_ttl_hours: float) -> "SafetyEvent":
        if self.expires_at is None:
            self.expires_at = self.timestamp + timedelta(hours=default_ttl_hours)
        return self

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or utcnow()
        return self.expires_at is not None and now >= self.expires_at


# ---------------------------------------------------------------------------
# Crime records
# ---------------------------------------------------------------------------

class CrimeRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crime_"))
    latitude: float
    longitude: float
    category: str
    severity: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime
    label: DataLabel = DataLabel.SIMULATED
    polygon: Optional[List[List[float]]] = None  # optional [[lat,lng],...] area instead of point


# ---------------------------------------------------------------------------
# Points of interest
# ---------------------------------------------------------------------------

class PointOfInterest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("poi_"))
    type: Literal["police", "hospital", "emergency", "safe_place", "business", "transport", "cctv_camera"]
    name: str
    latitude: float
    longitude: float
    label: DataLabel = DataLabel.SIMULATED
    open_now: Optional[bool] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Route segmentation & scoring
# ---------------------------------------------------------------------------

class SegmentScoreBreakdown(BaseModel):
    crime: float
    lighting: float
    footfall: float
    cctv: float
    police_proximity: float
    hospital_proximity: float
    incidents: float
    connectivity: float
    environmental: float
    cv_anomaly: float
    road_type: float
    isolation: float
    time_of_day: float

    def as_dict(self) -> Dict[str, float]:
        return self.model_dump()


class RouteSegment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("seg_"))
    sequence_index: int
    start: LatLng
    end: LatLng
    geometry: List[LatLng]  # full polyline for this segment
    distance_m: float
    road_type: RoadType
    scores: SegmentScoreBreakdown
    overall_safety_score: float = Field(..., ge=0.0, le=100.0)
    risk_level: RiskLevel
    confidence: float = Field(..., ge=0.0, le=1.0)
    positive_factors: List[str] = Field(default_factory=list)
    negative_factors: List[str] = Field(default_factory=list)
    data_labels: Dict[str, DataLabel] = Field(default_factory=dict)


class RouteCandidate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("route_"))
    geometry: List[LatLng]
    distance_m: float
    estimated_duration_s: float
    provider: str = "demo"


class ScoredRoute(BaseModel):
    id: str
    geometry: List[LatLng]
    distance_m: float
    estimated_duration_s: float
    overall_safety_score: float
    risk_level: RiskLevel
    confidence: float
    segments: List[RouteSegment]
    positive_factors: List[str]
    negative_factors: List[str]
    label_summary: Dict[str, int] = Field(default_factory=dict)  # count of REAL/SIMULATED/etc used


class SafeRouteResult(BaseModel):
    request_id: str = Field(default_factory=lambda: new_id("req_"))
    generated_at: datetime = Field(default_factory=utcnow)
    origin: LatLng
    destination: LatLng
    recommended_route: ScoredRoute
    alternative_routes: List[ScoredRoute]
    all_routes_ranked: List[str]  # route ids best -> worst


class DynamicRouteUpdate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("upd_"))
    generated_at: datetime = Field(default_factory=utcnow)
    reason: str
    previous_route_id: str
    previous_score: float
    new_score: float
    triggering_event_ids: List[str] = Field(default_factory=list)
    alternative_route: Optional[ScoredRoute] = None
    recommendation: str


# ---------------------------------------------------------------------------
# API request bodies
# ---------------------------------------------------------------------------

class SafeRouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    current_location: Optional[LatLng] = None
    departure_time: Optional[datetime] = None
    max_alternatives: int = 2


class AreaSafetyRequest(BaseModel):
    center: LatLng
    radius_m: float = 500.0
    at_time: Optional[datetime] = None


class ScoreGeometryRequest(BaseModel):
    """Score a real, externally-sourced route (e.g. from OSRM/Google
    Directions) instead of one of Guardian's own synthetic candidates."""
    geometry: List[LatLng]
    at_time: Optional[datetime] = None
    provider: str = "external"
    estimated_duration_s: Optional[float] = None
