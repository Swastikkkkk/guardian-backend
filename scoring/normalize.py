"""Normalization primitives. Every raw signal becomes a 0..1 float here
before it ever reaches the weighted-sum aggregator, per the module spec's
"every parameter must be independently normalized" requirement."""
from __future__ import annotations
from typing import Iterable


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def inverse(x: float) -> float:
    """Flip a 0..1 'risk' value into a 0..1 'safety' value."""
    return clamp01(1.0 - x)


def normalize_count(count: int, saturate_at: int) -> float:
    """0..1, saturating - e.g. 3+ police stations nearby is 'as good as 5'."""
    if saturate_at <= 0:
        return 0.0
    return clamp01(count / saturate_at)


def normalize_distance_inverse(distance_m: float, ideal_m: float, max_useful_m: float) -> float:
    """Closer is better. 1.0 at/below ideal_m, decays linearly to 0 at max_useful_m."""
    if distance_m <= ideal_m:
        return 1.0
    if distance_m >= max_useful_m:
        return 0.0
    span = max_useful_m - ideal_m
    return clamp01(1.0 - (distance_m - ideal_m) / span)


def weighted_mean(pairs: Iterable[tuple]) -> tuple:
    """pairs: iterable of (value, weight, available:bool).
    Returns (score 0..1, confidence 0..1) where confidence reflects how
    much of the total weight was actually backed by available data -
    this is how 'missing data' becomes UNKNOWN rather than a fabricated
    good/bad score."""
    total_weight = 0.0
    available_weight = 0.0
    weighted_sum = 0.0
    for value, weight, available in pairs:
        total_weight += weight
        if available:
            available_weight += weight
            weighted_sum += value * weight
    if available_weight == 0:
        return 0.5, 0.0  # neutral, zero confidence
    score = weighted_sum / available_weight
    confidence = available_weight / total_weight if total_weight > 0 else 0.0
    return clamp01(score), clamp01(confidence)
