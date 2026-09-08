"""Aggregates per-segment scores into a whole-route ScoredRoute, with an
overall explainable score, risk level, and top factors."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from typing import List

from config.weights import EngineConfig, DEFAULT_CONFIG
from models.enums import RiskLevel
from models.schemas import RouteCandidate, RouteSegment, ScoredRoute
from geospatial.utils import split_into_segments
from providers.registry import ProviderRegistry
from scoring.segment_scoring import score_segment


def segment_route(candidate: RouteCandidate, config: EngineConfig = DEFAULT_CONFIG) -> List[List]:
    return split_into_segments(candidate.geometry, config.segment_target_length_m)


_TOPIC_KEYWORDS = {
    "cctv": ["cctv"],
    "lighting": ["lit ", "lighting", "well-lit"],
    "footfall": ["activity", "footfall", "pedestrian activity"],
    "road_type": ["road classified", "main road", "residential road", "pedestrian road",
                  "highway road", "isolated road", "unpaved road"],
    "police": ["police"],
    "incidents": ["incident"],
    "crime": ["crime report"],
    "weather": ["weather"],
    "connectivity": ["connectivity"],
    "isolation": ["isolation"],
    "time_of_day": ["time window", "night"],
    "cv_anomaly": ["anomaly"],
    "road_condition": ["road surface"],
}

_TOPIC_LABELS = {
    "cctv": "CCTV coverage", "lighting": "Street lighting", "footfall": "Foot traffic",
    "road_type": "Road type", "police": "Police proximity", "incidents": "Recent incidents",
    "crime": "Historical crime reports", "weather": "Weather", "connectivity": "Network connectivity",
    "isolation": "Route isolation", "time_of_day": "Time of day", "cv_anomaly": "CCTV anomaly activity",
    "road_condition": "Road surface condition",
}


def _topic_of(factor: str) -> str:
    low = factor.lower()
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return topic
    return low  # no known topic -> treat as unique, never collides


def _resolve_contradictions(positives: List[str], negatives: List[str]) -> tuple:
    """Route-level positive/negative factors are drawn independently from
    the best and worst segments, so the SAME topic (e.g. CCTV) can
    legitimately be a strength in one part of the route and a weakness in
    another. Left as-is, that reads as a nonsensical contradiction
    ("Strong CCTV coverage" next to "Limited CCTV coverage"). Instead,
    fold any overlapping topic into a single honest "varies along the
    route" statement rather than showing both halves side by side."""
    pos_topics = {_topic_of(p): p for p in positives}
    neg_topics = {_topic_of(n): n for n in negatives}
    overlap = set(pos_topics) & set(neg_topics)
    if not overlap:
        return positives, negatives

    new_positives = [p for p in positives if _topic_of(p) not in overlap]
    new_negatives = [n for n in negatives if _topic_of(n) not in overlap]
    varies_notes = [
        f"{_TOPIC_LABELS.get(topic, topic.title())} varies along the route - "
        f"stronger in some sections, weaker in others"
        for topic in overlap
    ]
    return new_positives, varies_notes + new_negatives


def score_route(
    candidate: RouteCandidate,
    at_time: datetime,
    registry: ProviderRegistry,
    config: EngineConfig = DEFAULT_CONFIG,
) -> ScoredRoute:
    if at_time.tzinfo is None:
        at_time = at_time.replace(tzinfo=timezone.utc)

    sub_polylines = segment_route(candidate, config)
    segments: List[RouteSegment] = [
        score_segment(i, geom, at_time, registry, config)
        for i, geom in enumerate(sub_polylines)
        if len(geom) >= 2
    ]

    if not segments:
        raise ValueError("Route produced no scorable segments - check candidate.geometry")

    total_distance = sum(s.distance_m for s in segments) or 1.0
    weighted_score = sum(s.overall_safety_score * s.distance_m for s in segments) / total_distance
    weighted_confidence = sum(s.confidence * s.distance_m for s in segments) / total_distance

    if weighted_confidence < config.thresholds.unknown_confidence_min:
        risk_level = RiskLevel.UNKNOWN
    elif weighted_score >= config.thresholds.safe_min:
        risk_level = RiskLevel.SAFE
    elif weighted_score >= config.thresholds.caution_min:
        risk_level = RiskLevel.CAUTION
    else:
        risk_level = RiskLevel.HIGH_RISK

    worst_segments = sorted(segments, key=lambda s: s.overall_safety_score)[:max(1, len(segments) // 3)]
    negative_counter = Counter()
    for s in worst_segments:
        for f in s.negative_factors:
            negative_counter[f] += 1
    positive_counter = Counter()
    best_segments = sorted(segments, key=lambda s: -s.overall_safety_score)[:max(1, len(segments) // 3)]
    for s in best_segments:
        for f in s.positive_factors:
            positive_counter[f] += 1

    negatives = [f for f, _ in negative_counter.most_common(6)]
    positives = [f for f, _ in positive_counter.most_common(6)]
    positives, negatives = _resolve_contradictions(positives, negatives)

    label_summary = Counter()
    for s in segments:
        for label in s.data_labels.values():
            label_summary[label.value] += 1

    return ScoredRoute(
        id=candidate.id,
        geometry=candidate.geometry,
        distance_m=candidate.distance_m,
        estimated_duration_s=candidate.estimated_duration_s,
        overall_safety_score=round(weighted_score, 1),
        risk_level=risk_level,
        confidence=round(weighted_confidence, 3),
        segments=segments,
        positive_factors=positives,
        negative_factors=negatives,
        label_summary=dict(label_summary),
    )
