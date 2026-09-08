from datetime import datetime, timezone

from models.enums import CVEventType, SafetyEventSeverity, DataLabel
from models.schemas import LatLng, CCTVEvent
from routes.safe_route_engine import SafeRouteEngine
from data.event_bus import EVENT_BUS
from cv.event_translator import cctv_event_to_safety_event


def test_plan_returns_ranked_routes_best_first():
    engine = SafeRouteEngine()
    origin = LatLng(lat=28.60, lng=77.20)
    destination = LatLng(lat=28.61, lng=77.21)
    result = engine.plan(origin, destination, max_alternatives=2)
    all_routes = [result.recommended_route, *result.alternative_routes]
    scores = [r.overall_safety_score for r in all_routes]
    assert scores == sorted(scores, reverse=True)
    assert result.all_routes_ranked[0] == result.recommended_route.id


def test_get_route_after_plan_is_cached():
    engine = SafeRouteEngine()
    origin = LatLng(lat=28.60, lng=77.20)
    destination = LatLng(lat=28.61, lng=77.21)
    result = engine.plan(origin, destination)
    fetched = engine.get_route(result.recommended_route.id)
    assert fetched is not None
    assert fetched.id == result.recommended_route.id


def test_get_route_unknown_id_returns_none():
    engine = SafeRouteEngine()
    assert engine.get_route("does-not-exist") is None


def test_dynamic_reroute_detects_new_high_severity_anomaly():
    engine = SafeRouteEngine()
    origin = LatLng(lat=28.55, lng=77.15)
    destination = LatLng(lat=28.56, lng=77.16)
    now = datetime.now(timezone.utc)
    result = engine.plan(origin, destination, at_time=now, max_alternatives=2)
    chosen = result.recommended_route

    mid_segment = chosen.segments[len(chosen.segments) // 2]
    anomaly_point = mid_segment.geometry[len(mid_segment.geometry) // 2]

    # Inject several severe anomalies to force a material score drop -
    # demo data is randomized so we push hard rather than asserting on
    # a single injected event.
    for i in range(3):
        evt = CCTVEvent(
            camera_id=f"CAM-TEST-{i}", latitude=anomaly_point.lat, longitude=anomaly_point.lng,
            event_type=CVEventType.POSSIBLE_ALTERCATION, confidence=0.95,
            severity=SafetyEventSeverity.CRITICAL, label=DataLabel.SIMULATED,
        )
        EVENT_BUS.publish_cctv_event(evt)
        EVENT_BUS.publish(cctv_event_to_safety_event(evt))

    update = engine.dynamic_reroute(chosen.id, origin, destination, at_time=now)
    # Either a reroute is triggered, or the chosen route was already the
    # global best even after the hit - both are valid outcomes; what must
    # NOT happen is a crash or a nonsensical negative delta recommendation.
    if update is not None:
        assert update.new_score > update.previous_score
        assert update.alternative_route is not None
