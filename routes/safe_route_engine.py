"""
SafeRouteEngine: the top-level orchestrator.

Given origin/destination/time, generates candidate routes, scores each
one (delegating to scoring/route_scoring.py), ranks them, and returns a
SafeRouteResult. Also supports dynamic re-evaluation when new safety
data arrives (dynamic_reroute), producing a DynamicRouteUpdate the
iPhone app can surface as "Safer route available."
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional

from config.weights import EngineConfig, DEFAULT_CONFIG
from models.schemas import (
    LatLng, SafeRouteResult, ScoredRoute, DynamicRouteUpdate, RouteCandidate,
)
from providers.registry import ProviderRegistry, DEFAULT_REGISTRY
from routes.candidate_generator import DemoRouteProvider
from scoring.route_scoring import score_route


class SafeRouteEngine:
    def __init__(
        self,
        registry: ProviderRegistry = DEFAULT_REGISTRY,
        route_provider: DemoRouteProvider = None,
        config: EngineConfig = DEFAULT_CONFIG,
    ):
        self.registry = registry
        self.route_provider = route_provider or DemoRouteProvider()
        self.config = config
        # request_id -> {route_id -> ScoredRoute} so /route/{id} and dynamic
        # rerouting can look routes back up after the initial request.
        self._route_cache: dict[str, ScoredRoute] = {}

    def plan(
        self,
        origin: LatLng,
        destination: LatLng,
        at_time: Optional[datetime] = None,
        max_alternatives: int = 2,
    ) -> SafeRouteResult:
        at_time = at_time or datetime.now(timezone.utc)
        candidate_count = min(self.config.max_alternative_routes, max_alternatives + 1)
        candidates: List[RouteCandidate] = self.route_provider.generate_candidates(
            origin, destination, count=max(2, candidate_count)
        )

        scored = [score_route(c, at_time, self.registry, self.config) for c in candidates]
        scored.sort(key=lambda r: (-r.overall_safety_score, r.estimated_duration_s))

        for r in scored:
            self._route_cache[r.id] = r

        recommended, alternatives = scored[0], scored[1:]
        return SafeRouteResult(
            origin=origin, destination=destination,
            recommended_route=recommended, alternative_routes=alternatives,
            all_routes_ranked=[r.id for r in scored],
        )

    def get_route(self, route_id: str) -> Optional[ScoredRoute]:
        return self._route_cache.get(route_id)

    def dynamic_reroute(
        self,
        active_route_id: str,
        origin: LatLng,
        destination: LatLng,
        at_time: Optional[datetime] = None,
        triggering_event_ids: Optional[List[str]] = None,
    ) -> Optional[DynamicRouteUpdate]:
        """Re-scores the active route against fresh live data and, if a
        materially safer alternative now exists, returns a
        DynamicRouteUpdate. Returns None if nothing material changed."""
        at_time = at_time or datetime.now(timezone.utc)
        previous = self._route_cache.get(active_route_id)
        if previous is None:
            return None

        result = self.plan(origin, destination, at_time=at_time, max_alternatives=self.config.max_alternative_routes - 1)
        # Re-score the SAME geometry as `previous` to get a fresh score
        # reflecting newly published events, independent of ranking.
        refreshed_active = next((r for r in [result.recommended_route, *result.alternative_routes]
                                  if r.id == active_route_id), None)
        if refreshed_active is None:
            # active route wasn't regenerated (candidate generator is
            # nondeterministic-by-index in real routing); fall back to
            # comparing previous score against the newly recommended route.
            refreshed_active_score = previous.overall_safety_score
        else:
            refreshed_active_score = refreshed_active.overall_safety_score

        best = result.recommended_route
        delta = best.overall_safety_score - refreshed_active_score

        if best.id == active_route_id or delta < self.config.rerouting_score_delta_trigger:
            return None

        return DynamicRouteUpdate(
            reason="New safety data lowered the current route's score relative to an available alternative.",
            previous_route_id=active_route_id,
            previous_score=refreshed_active_score,
            new_score=best.overall_safety_score,
            triggering_event_ids=triggering_event_ids or [],
            alternative_route=best,
            recommendation=f"Safer route available (+{delta:.0f} pts). Consider switching.",
        )


# Process-wide singleton for the API layer.
ENGINE = SafeRouteEngine()
