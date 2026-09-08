"""Translates raw CCTVEvents into SafetyEvents for the unified live pipeline,
and provides the severity/confidence mapping used by the scoring engine."""
from __future__ import annotations
from datetime import timedelta

from models.enums import CVEventType, SafetyEventSeverity, SafetyEventSource, DataLabel
from models.schemas import CCTVEvent, SafetyEvent, LatLng

# Base severity per event type - tune here, not inline in the engine.
CV_EVENT_BASE_SEVERITY = {
    CVEventType.PERSON_DETECTED: SafetyEventSeverity.LOW,
    CVEventType.CROWD_INCREASE: SafetyEventSeverity.LOW,
    CVEventType.UNUSUAL_CROWD_BEHAVIOR: SafetyEventSeverity.MEDIUM,
    CVEventType.RUNNING_OR_CHASING: SafetyEventSeverity.HIGH,
    CVEventType.POSSIBLE_ALTERCATION: SafetyEventSeverity.HIGH,
    CVEventType.FALL: SafetyEventSeverity.MEDIUM,
    CVEventType.UNUSUAL_MOVEMENT: SafetyEventSeverity.MEDIUM,
    CVEventType.ROUTE_OBSTRUCTION: SafetyEventSeverity.MEDIUM,
    CVEventType.SUSPICIOUS_PERSISTENT_MOVEMENT: SafetyEventSeverity.HIGH,
    CVEventType.OTHER_ANOMALY: SafetyEventSeverity.LOW,
}

# How much a fully-confident event of each severity should erode a
# 0..1 "cv_anomaly" safety score (1.0 = no anomaly detected).
SEVERITY_IMPACT = {
    SafetyEventSeverity.LOW: 0.15,
    SafetyEventSeverity.MEDIUM: 0.35,
    SafetyEventSeverity.HIGH: 0.60,
    SafetyEventSeverity.CRITICAL: 0.85,
}

CV_EVENT_TTL_HOURS = {
    SafetyEventSeverity.LOW: 1.0,
    SafetyEventSeverity.MEDIUM: 3.0,
    SafetyEventSeverity.HIGH: 6.0,
    SafetyEventSeverity.CRITICAL: 12.0,
}


def cctv_event_to_safety_event(evt: CCTVEvent) -> SafetyEvent:
    ttl = CV_EVENT_TTL_HOURS.get(evt.severity, 2.0)
    return SafetyEvent(
        timestamp=evt.timestamp,
        location=LatLng(lat=evt.latitude, lng=evt.longitude),
        source=SafetyEventSource.CCTV,
        type=evt.event_type.value,
        severity=evt.severity,
        confidence=evt.confidence,
        expires_at=evt.timestamp + timedelta(hours=ttl),
        label=evt.label,
        metadata={"camera_id": evt.camera_id, "cctv_event_id": evt.id},
    )


def cv_anomaly_impact(evt: CCTVEvent) -> float:
    """0..1 erosion amount this single event contributes (before decay)."""
    return SEVERITY_IMPACT.get(evt.severity, 0.2) * evt.confidence
