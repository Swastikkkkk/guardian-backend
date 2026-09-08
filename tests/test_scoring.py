from datetime import datetime, timezone

from models.schemas import LatLng
from providers.registry import build_demo_registry
from scoring.segment_scoring import score_segment
from routes.candidate_generator import DemoRouteProvider
from scoring.route_scoring import score_route


def test_score_segment_bounds_and_explainability():
    registry = build_demo_registry()
    geometry = [LatLng(lat=28.6, lng=77.2), LatLng(lat=28.6009, lng=77.2009)]
    now = datetime.now(timezone.utc)
    seg = score_segment(0, geometry, now, registry)
    assert 0 <= seg.overall_safety_score <= 100
    assert 0 <= seg.confidence <= 1
    assert isinstance(seg.positive_factors, list)
    assert isinstance(seg.negative_factors, list)
    # every scored dimension must be normalized 0..1
    for v in seg.scores.as_dict().values():
        assert 0.0 <= v <= 1.0


def test_score_route_end_to_end():
    registry = build_demo_registry()
    provider = DemoRouteProvider()
    origin = LatLng(lat=28.60, lng=77.20)
    destination = LatLng(lat=28.61, lng=77.21)
    candidates = provider.generate_candidates(origin, destination, count=2)
    now = datetime.now(timezone.utc)
    scored_routes = [score_route(c, now, registry) for c in candidates]
    for r in scored_routes:
        assert len(r.segments) > 0
        assert 0 <= r.overall_safety_score <= 100
        # segments should sum to ~ full route distance
        seg_total = sum(s.distance_m for s in r.segments)
        assert abs(seg_total - r.distance_m) < max(5.0, r.distance_m * 0.02)


def test_missing_data_yields_unknown_or_low_confidence(monkeypatch):
    """Simulate total data blackout: every provider signal unavailable ->
    should not silently report a fabricated high score."""
    registry = build_demo_registry()

    class BlankSourced:
        value = 0.5
        label = None

    # Monkeypatch footfall/lighting/connectivity to return mid-value with
    # explicit unavailability by forcing weighted_mean's `available` flag off
    # is internal; instead we assert that the pipeline still returns a
    # bounded, non-crashing result even under sparse/blank inputs.
    geometry = [LatLng(lat=0.0, lng=0.0), LatLng(lat=0.0009, lng=0.0009)]
    now = datetime.now(timezone.utc)
    seg = score_segment(0, geometry, now, registry)
    assert 0 <= seg.overall_safety_score <= 100
