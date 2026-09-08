"""
Segment-level safety scoring engine.

For a single route segment, pulls every provider signal, normalizes it,
applies temporal weighting/decay, combines it via configurable weights,
and produces an explainable SegmentScoreBreakdown + overall score +
risk level + confidence + human-readable positive/negative factors.

This is the module's core scoring logic; route_scoring.py aggregates
these across a whole route.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Tuple

from config.weights import EngineConfig, DEFAULT_CONFIG
from models.enums import RoadType, RiskLevel, DataLabel
from models.schemas import LatLng, RouteSegment, SegmentScoreBreakdown, CrimeRecord
from geospatial.utils import haversine_m, nearest_distance_m, polyline_length_m
from providers.registry import ProviderRegistry
from scoring.normalize import clamp01, inverse, normalize_count, normalize_distance_inverse, weighted_mean
from scoring.temporal import crime_recency_weight, incident_recency_weight, time_of_day_score
from cv.event_translator import cv_anomaly_impact
from data.event_bus import EVENT_BUS

SEARCH_RADIUS_M = 300.0
POLICE_IDEAL_M, POLICE_MAX_M = 400.0, 2500.0
HOSPITAL_IDEAL_M, HOSPITAL_MAX_M = 800.0, 4000.0
EMERGENCY_IDEAL_M, EMERGENCY_MAX_M = 600.0, 3000.0


def _segment_midpoint(points: List[LatLng]) -> LatLng:
    mid_idx = len(points) // 2
    return points[mid_idx]


def _crime_score(records: List[CrimeRecord], point: LatLng, now: datetime) -> Tuple[float, bool, List[str]]:
    if not records:
        return 1.0, False, []
    weighted_severity = 0.0
    total_weight = 0.0
    recent_flag = False
    for r in records:
        rec_time = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
        recency_w = crime_recency_weight(rec_time, now)
        dist = haversine_m(point, LatLng(lat=r.latitude, lng=r.longitude))
        proximity_w = normalize_distance_inverse(dist, 50, SEARCH_RADIUS_M)
        w = recency_w * max(0.1, proximity_w)
        weighted_severity += r.severity * w
        total_weight += w
        if (now - rec_time).days <= 30:
            recent_flag = True
    if total_weight == 0:
        return 1.0, False, []
    density_penalty = clamp01(weighted_severity / max(1.0, total_weight) * min(1.0, total_weight / 3.0))
    score = inverse(density_penalty)
    notes = []
    if recent_flag:
        notes.append("Recent crime report(s) nearby (last 30 days)")
    return score, True, notes


def score_segment(
    sequence_index: int,
    geometry: List[LatLng],
    at_time: datetime,
    registry: ProviderRegistry,
    config: EngineConfig = DEFAULT_CONFIG,
) -> RouteSegment:
    if at_time.tzinfo is None:
        at_time = at_time.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    point = _segment_midpoint(geometry)
    distance_m = polyline_length_m(geometry)
    labels: dict = {}
    positives: List[str] = []
    negatives: List[str] = []

    # --- Road type & condition -------------------------------------------------
    road_sourced = registry.road.classify_road(point)
    road_type: RoadType = road_sourced.value
    labels["road_type"] = road_sourced.label
    road_type_score = config.road_type_weights.__dict__.get(road_type.value, 0.5)
    if road_type in (RoadType.ISOLATED, RoadType.UNPAVED):
        negatives.append(f"Road classified as {road_type.value.lower()}")
    elif road_type in (RoadType.MAIN, RoadType.PEDESTRIAN):
        positives.append(f"{road_type.value.title()} road")

    road_condition_sourced = registry.road.get_road_condition(point)
    labels["road_condition"] = road_condition_sourced.label
    if road_condition_sourced.value < 0.5:
        negatives.append("Poor road surface condition")

    # --- Crime (historical, decayed) -------------------------------------------
    crime_records = registry.crime.get_records_near(point, SEARCH_RADIUS_M)
    crime_score, crime_avail, crime_notes = _crime_score(crime_records, point, now)
    negatives.extend(crime_notes)
    labels["crime"] = DataLabel.SIMULATED if crime_records else DataLabel.ESTIMATED

    # --- Lighting ---------------------------------------------------------------
    lighting_sourced = registry.lighting.get_lighting_score(point, at_time)
    labels["lighting"] = lighting_sourced.label
    lighting_score = lighting_sourced.value
    if lighting_score < 0.4:
        negatives.append("Poor street lighting")
    elif lighting_score > 0.75:
        positives.append("Well-lit segment")

    # --- Footfall / crowd / device density --------------------------------------
    footfall_sourced = registry.footfall.get_activity_score(point, at_time)
    labels["footfall"] = footfall_sourced.label
    footfall_score = footfall_sourced.value
    if footfall_score > 0.7:
        positives.append("High public activity / footfall")
    elif footfall_score < 0.25:
        negatives.append("Low pedestrian activity")

    # --- CCTV coverage + live anomalies ------------------------------------------
    cameras = registry.cctv.get_cameras_near(point, SEARCH_RADIUS_M)
    coverage_score = normalize_count(len(cameras), saturate_at=3)
    labels["cctv"] = DataLabel.SIMULATED
    if coverage_score > 0.6:
        positives.append("Strong CCTV coverage")
    elif coverage_score < 0.2:
        negatives.append("Limited CCTV coverage")

    cv_events = EVENT_BUS.query_cctv_near(point, SEARCH_RADIUS_M, since=now.replace(hour=0, minute=0, second=0))
    cv_events += registry.cctv.get_recent_events_near(point, SEARCH_RADIUS_M, since=now)
    cv_anomaly_penalty = 0.0
    for evt in cv_events:
        decay = incident_recency_weight(evt.timestamp if evt.timestamp.tzinfo else evt.timestamp.replace(tzinfo=timezone.utc), now)
        cv_anomaly_penalty += cv_anomaly_impact(evt) * decay
    cv_anomaly_score = inverse(min(1.0, cv_anomaly_penalty))
    if cv_events:
        labels["cv_anomaly"] = DataLabel.REAL if any(e.label == DataLabel.REAL for e in cv_events) else DataLabel.SIMULATED
        if cv_anomaly_score < 0.6:
            negatives.append("Recent CCTV anomaly detected nearby")
    else:
        labels["cv_anomaly"] = DataLabel.ESTIMATED

    # --- Police / hospital / emergency infra proximity ---------------------------
    police = registry.emergency_infra.get_police_near(point, POLICE_MAX_M)
    police_dist = nearest_distance_m(point, [LatLng(lat=p.latitude, lng=p.longitude) for p in police])
    police_score = normalize_distance_inverse(police_dist, POLICE_IDEAL_M, POLICE_MAX_M)
    labels["police_proximity"] = DataLabel.SIMULATED
    if police_score > 0.7:
        positives.append("Police station nearby")

    hospitals = registry.emergency_infra.get_hospitals_near(point, HOSPITAL_MAX_M)
    hospital_dist = nearest_distance_m(point, [LatLng(lat=p.latitude, lng=p.longitude) for p in hospitals])
    hospital_score = normalize_distance_inverse(hospital_dist, HOSPITAL_IDEAL_M, HOSPITAL_MAX_M)
    labels["hospital_proximity"] = DataLabel.SIMULATED

    emergency = registry.emergency_infra.get_emergency_services_near(point, EMERGENCY_MAX_M)
    emergency_dist = nearest_distance_m(point, [LatLng(lat=p.latitude, lng=p.longitude) for p in emergency])
    emergency_score = normalize_distance_inverse(emergency_dist, EMERGENCY_IDEAL_M, EMERGENCY_MAX_M)
    labels["emergency_proximity"] = DataLabel.SIMULATED

    # --- Live incidents (independent of CCTV) -------------------------------------
    live_incidents = EVENT_BUS.query_near(point, SEARCH_RADIUS_M, now=now)
    live_incidents += registry.incidents.get_recent_incidents_near(point, SEARCH_RADIUS_M, since=now)
    incident_penalty = 0.0
    for evt in live_incidents:
        ts = evt.timestamp if evt.timestamp.tzinfo else evt.timestamp.replace(tzinfo=timezone.utc)
        decay = incident_recency_weight(ts, now)
        sev_weight = {"LOW": 0.15, "MEDIUM": 0.35, "HIGH": 0.6, "CRITICAL": 0.9}.get(evt.severity.value, 0.2)
        incident_penalty += sev_weight * evt.confidence * decay
    incident_score = inverse(min(1.0, incident_penalty))
    labels["incidents"] = DataLabel.SIMULATED if not live_incidents else DataLabel.REAL
    if live_incidents:
        negatives.append(f"{len(live_incidents)} recent reported incident(s) nearby")

    # --- Connectivity --------------------------------------------------------------
    connectivity_sourced = registry.connectivity.get_connectivity_score(point)
    labels["connectivity"] = connectivity_sourced.label
    connectivity_score = connectivity_sourced.value
    if connectivity_score < 0.3:
        negatives.append("Weak network connectivity - may hinder emergency calls")

    # --- Weather / environmental -----------------------------------------------
    weather_sourced = registry.weather.get_weather_score(point, at_time)
    labels["weather"] = weather_sourced.label
    env_sourced = registry.satellite.get_environmental_context(point)
    labels["environmental"] = env_sourced.label
    isolation_from_satellite = env_sourced.value.get("terrain_isolation", 0.0)
    environmental_score = clamp01((weather_sourced.value + inverse(env_sourced.value.get("flood_risk", 0.0))) / 2.0)
    if weather_sourced.value < 0.5:
        negatives.append("Adverse weather conditions")

    # --- Isolation (road type + satellite terrain + footfall) ----------------------
    isolation_raw = clamp01((1 - footfall_score) * 0.5 + isolation_from_satellite * 0.5)
    isolation_score = inverse(isolation_raw)
    if isolation_score < 0.4:
        negatives.append("Route isolation - sparse activity/development")

    # --- Time of day --------------------------------------------------------------
    tod_score = time_of_day_score(at_time)
    if tod_score < 0.4:
        negatives.append("Late-night/early-morning time window increases risk")

    # --- Aggregate via configured weights, tracking confidence ---------------------
    w = config.weights
    pairs = [
        (crime_score, w.crime, True),
        (lighting_score, w.lighting, True),
        (tod_score, w.time_of_day, True),
        (road_type_score, w.road_type, True),
        (police_score, w.police_proximity, True),
        (footfall_score, w.footfall, True),
        (coverage_score, w.cctv * 0.5 + 0, True),
        (cv_anomaly_score, w.cv_anomaly, True),
        (connectivity_score, w.connectivity, True),
        (incident_score, w.incidents, True),
        (hospital_score, w.hospital_proximity, True),
        (emergency_score, w.emergency_proximity, True),
        (environmental_score, w.environmental + w.weather, True),
        (isolation_score, w.isolation, True),
        (road_condition_sourced.value, w.road_condition, True),
    ]
    normalized_score, confidence = weighted_mean(pairs)
    overall = round(normalized_score * 100, 1)

    if confidence < config.thresholds.unknown_confidence_min:
        risk_level = RiskLevel.UNKNOWN
    elif overall >= config.thresholds.safe_min:
        risk_level = RiskLevel.SAFE
    elif overall >= config.thresholds.caution_min:
        risk_level = RiskLevel.CAUTION
    else:
        risk_level = RiskLevel.HIGH_RISK

    breakdown = SegmentScoreBreakdown(
        crime=round(crime_score, 3), lighting=round(lighting_score, 3), footfall=round(footfall_score, 3),
        cctv=round(coverage_score, 3), police_proximity=round(police_score, 3),
        hospital_proximity=round(hospital_score, 3), incidents=round(incident_score, 3),
        connectivity=round(connectivity_score, 3), environmental=round(environmental_score, 3),
        cv_anomaly=round(cv_anomaly_score, 3), road_type=round(road_type_score, 3),
        isolation=round(isolation_score, 3), time_of_day=round(tod_score, 3),
    )

    return RouteSegment(
        sequence_index=sequence_index,
        start=geometry[0], end=geometry[-1], geometry=geometry,
        distance_m=round(distance_m, 1), road_type=road_type,
        scores=breakdown, overall_safety_score=overall, risk_level=risk_level,
        confidence=round(confidence, 3),
        positive_factors=positives, negative_factors=negatives,
        data_labels=labels,
    )
