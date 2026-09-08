"""
Provider interfaces (abstract base classes).

Every external data source Guardian consumes sits behind one of these
interfaces. Nothing in /scoring or /routes ever imports a concrete
provider directly - it depends on these ABCs, so a real API integration
can replace the demo/simulated implementation later without touching
the scoring engine.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from models.schemas import (
    LatLng, CrimeRecord, PointOfInterest, SafetyEvent, CCTVEvent, Sourced,
)


class CrimeDataProvider(ABC):
    @abstractmethod
    def get_records_near(self, point: LatLng, radius_m: float, since: Optional[datetime] = None) -> List[CrimeRecord]:
        ...


class LightingDataProvider(ABC):
    @abstractmethod
    def get_lighting_score(self, point: LatLng, at_time: datetime) -> Sourced:
        """Returns Sourced[float 0..1] lighting quality at a point/time."""
        ...


class RoadDataProvider(ABC):
    @abstractmethod
    def classify_road(self, point: LatLng) -> Sourced:
        """Returns Sourced[RoadType]."""
        ...

    @abstractmethod
    def get_road_condition(self, point: LatLng) -> Sourced:
        """Returns Sourced[float 0..1], 1.0 = excellent condition."""
        ...


class FootfallDataProvider(ABC):
    @abstractmethod
    def get_activity_score(self, point: LatLng, at_time: datetime) -> Sourced:
        """Returns Sourced[float 0..1] combining footfall/crowd/device density."""
        ...


class CCTVDataProvider(ABC):
    @abstractmethod
    def get_cameras_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        ...

    @abstractmethod
    def get_recent_events_near(self, point: LatLng, radius_m: float, since: datetime) -> List[CCTVEvent]:
        ...


class IncidentDataProvider(ABC):
    @abstractmethod
    def get_recent_incidents_near(self, point: LatLng, radius_m: float, since: datetime) -> List[SafetyEvent]:
        ...


class WeatherDataProvider(ABC):
    @abstractmethod
    def get_weather_score(self, point: LatLng, at_time: datetime) -> Sourced:
        """Returns Sourced[float 0..1], 1.0 = benign conditions."""
        ...


class ConnectivityDataProvider(ABC):
    @abstractmethod
    def get_connectivity_score(self, point: LatLng) -> Sourced:
        """Returns Sourced[float 0..1], 1.0 = strong network coverage."""
        ...


class SatelliteDataProvider(ABC):
    @abstractmethod
    def get_environmental_context(self, point: LatLng) -> Sourced:
        """Returns Sourced[dict] with keys like land_use, vegetation_density,
        flood_risk, terrain_isolation - contextual only, never authoritative."""
        ...


class SafePlaceDataProvider(ABC):
    @abstractmethod
    def get_safe_places_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        ...


class EmergencyInfrastructureProvider(ABC):
    @abstractmethod
    def get_police_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        ...

    @abstractmethod
    def get_hospitals_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        ...

    @abstractmethod
    def get_emergency_services_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        ...


class PublicTransportProvider(ABC):
    @abstractmethod
    def get_stops_near(self, point: LatLng, radius_m: float) -> List[PointOfInterest]:
        ...


class BusinessDataProvider(ABC):
    @abstractmethod
    def get_open_businesses_near(self, point: LatLng, radius_m: float, at_time: datetime) -> List[PointOfInterest]:
        ...
