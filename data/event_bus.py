"""
In-memory live event store: the "live data pipeline" backbone.

Every real-time signal (new incidents, CCTV anomalies, weather, traffic,
transport, crowd, connectivity, environmental events) is normalized into
a SafetyEvent and pushed here. Consumers (scoring engine, dynamic
rerouting) query by location/radius and get automatic TTL-based expiry -
an incident from two weeks ago is never treated like one from two
minutes ago because it will have already expired out of the active set.

This is intentionally a simple process-local store (thread-safe via a
lock) so the module runs with zero infra dependencies; swap for
Redis/Kafka/Postgres in production without changing callers, since they
only depend on the methods below.
"""
from __future__ import annotations
import threading
from datetime import datetime, timezone
from typing import List, Optional

from config.weights import DEFAULT_CONFIG
from geospatial.utils import haversine_m
from models.schemas import SafetyEvent, LatLng, CCTVEvent


class LiveEventBus:
    def __init__(self):
        self._events: List[SafetyEvent] = []
        self._cctv_events: List[CCTVEvent] = []
        self._lock = threading.Lock()

    # -- SafetyEvent (unified live signal) ----------------------------------

    def publish(self, event: SafetyEvent) -> SafetyEvent:
        event.ensure_expiry(DEFAULT_CONFIG.temporal.default_event_ttl_hours)
        with self._lock:
            self._events.append(event)
        return event

    def query_near(self, point: LatLng, radius_m: float, now: Optional[datetime] = None) -> List[SafetyEvent]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            snapshot = list(self._events)
        return [
            e for e in snapshot
            if not e.is_expired(now) and haversine_m(point, e.location) <= radius_m
        ]

    def all_active(self, now: Optional[datetime] = None) -> List[SafetyEvent]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            snapshot = list(self._events)
        return [e for e in snapshot if not e.is_expired(now)]

    def purge_expired(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            before = len(self._events)
            self._events = [e for e in self._events if not e.is_expired(now)]
            return before - len(self._events)

    # -- CCTV events ---------------------------------------------------------

    def publish_cctv_event(self, event: CCTVEvent) -> CCTVEvent:
        with self._lock:
            self._cctv_events.append(event)
        return event

    def query_cctv_near(self, point: LatLng, radius_m: float, since: Optional[datetime] = None) -> List[CCTVEvent]:
        with self._lock:
            snapshot = list(self._cctv_events)
        out = []
        for e in snapshot:
            if since and e.timestamp < since:
                continue
            if haversine_m(point, LatLng(lat=e.latitude, lng=e.longitude)) <= radius_m:
                out.append(e)
        return out


# Process-wide singleton (see docstring re: swapping for real infra later).
EVENT_BUS = LiveEventBus()
