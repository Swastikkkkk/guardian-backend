"""
Candidate route generation.

In production this would call a real routing engine (OSRM, Google
Directions, Mapbox, GraphHopper) that returns actual road-network
polylines. For demo/offline operation, this generates 2-3 plausible
candidate polylines between origin and destination by perturbing a
direct path - enough geometry diversity for the SafeRouteEngine to
segment, score, and meaningfully differentiate.

Swap `DemoRouteProvider` for a real one behind the same
`generate_candidates` signature and nothing downstream changes.
"""
from __future__ import annotations
import math
from typing import List

from models.schemas import LatLng, RouteCandidate
from geospatial.utils import haversine_m, interpolate


AVERAGE_WALK_SPEED_MPS = 1.35  # ~4.9 km/h


class DemoRouteProvider:
    def generate_candidates(self, origin: LatLng, destination: LatLng, count: int = 3) -> List[RouteCandidate]:
        base = self._direct_path(origin, destination, steps=12)
        candidates = [self._to_candidate(base, "demo-direct")]

        for i in range(1, count):
            offset_frac = 0.08 * i  # increasing lateral offset per alternative
            wiggled = self._lateral_offset_path(origin, destination, offset_frac, sign=(1 if i % 2 else -1), steps=14)
            candidates.append(self._to_candidate(wiggled, f"demo-alt-{i}"))
        return candidates[:count]

    def _direct_path(self, origin: LatLng, destination: LatLng, steps: int) -> List[LatLng]:
        return [interpolate(origin, destination, t / steps) for t in range(steps + 1)]

    def _lateral_offset_path(self, origin: LatLng, destination: LatLng, max_offset_frac: float, sign: int, steps: int) -> List[LatLng]:
        """Builds a path that bows away from the direct line, approximating
        a different street routing choice."""
        dlat = destination.lat - origin.lat
        dlng = destination.lng - origin.lng
        length = math.hypot(dlat, dlng) or 1e-9
        # perpendicular unit vector
        perp_lat, perp_lng = -dlng / length, dlat / length

        points = []
        for i in range(steps + 1):
            t = i / steps
            base = interpolate(origin, destination, t)
            bow = math.sin(t * math.pi) * max_offset_frac * length * sign
            points.append(LatLng(lat=base.lat + perp_lat * bow, lng=base.lng + perp_lng * bow))
        return points

    def _to_candidate(self, points: List[LatLng], provider_tag: str) -> RouteCandidate:
        distance = sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))
        duration = distance / AVERAGE_WALK_SPEED_MPS
        return RouteCandidate(
            id=f"route_{provider_tag}",
            geometry=points, distance_m=round(distance, 1),
            estimated_duration_s=round(duration, 1), provider=provider_tag,
        )
