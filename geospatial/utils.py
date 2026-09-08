"""Core geospatial math: distance, bearing, interpolation, segmentation."""
from __future__ import annotations
import math
from typing import List, Tuple

from models.schemas import LatLng

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(a: LatLng, b: LatLng) -> float:
    """Great-circle distance in meters between two lat/lng points."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlng = math.radians(b.lng - a.lng)
    h = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def polyline_length_m(points: List[LatLng]) -> float:
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def interpolate(a: LatLng, b: LatLng, t: float) -> LatLng:
    """Linear interpolation (good enough for short segments used here)."""
    return LatLng(lat=a.lat + (b.lat - a.lat) * t, lng=a.lng + (b.lng - a.lng) * t)


def split_into_segments(points: List[LatLng], target_length_m: float) -> List[List[LatLng]]:
    """Split a polyline into sub-polylines each approximately target_length_m long.

    Never returns an empty list for a non-trivial input; the last segment
    absorbs any remainder shorter than target_length_m.
    """
    if len(points) < 2:
        return [points] if points else []

    segments: List[List[LatLng]] = []
    current = [points[0]]
    accumulated = 0.0

    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        seg_len = haversine_m(prev, curr)
        remaining_in_leg = seg_len

        cursor = prev
        while accumulated + remaining_in_leg >= target_length_m:
            needed = target_length_m - accumulated
            t = needed / remaining_in_leg if remaining_in_leg > 0 else 1.0
            t = max(0.0, min(1.0, t))
            split_point = interpolate(cursor, curr, t)
            current.append(split_point)
            segments.append(current)
            current = [split_point]
            accumulated = 0.0
            remaining_in_leg = haversine_m(split_point, curr)
            cursor = split_point

        current.append(curr)
        accumulated += remaining_in_leg

    if len(current) >= 2:
        segments.append(current)
    return segments


def bounding_box(points: List[LatLng], pad_m: float = 0.0) -> Tuple[float, float, float, float]:
    """Returns (min_lat, min_lng, max_lat, max_lng)."""
    lats = [p.lat for p in points]
    lngs = [p.lng for p in points]
    pad_deg = pad_m / 111_320.0  # rough meters-per-degree latitude
    return (min(lats) - pad_deg, min(lngs) - pad_deg, max(lats) + pad_deg, max(lngs) + pad_deg)


def point_in_radius(center: LatLng, point: LatLng, radius_m: float) -> bool:
    return haversine_m(center, point) <= radius_m


def nearest_distance_m(point: LatLng, candidates: List[LatLng]) -> float:
    if not candidates:
        return float("inf")
    return min(haversine_m(point, c) for c in candidates)
