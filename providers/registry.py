"""
Provider registry: the single place that decides which concrete provider
implementation backs each interface.

Switching Guardian from demo to real data sources means changing this file
only - scoring/route code never imports a concrete provider.
"""
from __future__ import annotations
from dataclasses import dataclass

from providers.base import (
    CrimeDataProvider, LightingDataProvider, RoadDataProvider, FootfallDataProvider,
    CCTVDataProvider, IncidentDataProvider, WeatherDataProvider, ConnectivityDataProvider,
    SatelliteDataProvider, SafePlaceDataProvider, EmergencyInfrastructureProvider,
    PublicTransportProvider, BusinessDataProvider,
)
from providers.demo import (
    DemoCrimeDataProvider, DemoLightingDataProvider, DemoRoadDataProvider, DemoFootfallDataProvider,
    DemoCCTVDataProvider, DemoIncidentDataProvider, DemoWeatherDataProvider, DemoConnectivityDataProvider,
    DemoSatelliteDataProvider, DemoSafePlaceDataProvider, DemoEmergencyInfrastructureProvider,
    DemoPublicTransportProvider, DemoBusinessDataProvider,
)
from providers.osm import (
    OSMRoadDataProvider, OSMLightingDataProvider, OSMCCTVDataProvider,
    OSMEmergencyInfrastructureProvider, OSMSafePlaceDataProvider, OSMPublicTransportProvider,
    OSMActivityDensityProvider,
)
from providers.weather_real import OpenMeteoWeatherDataProvider


@dataclass
class ProviderRegistry:
    crime: CrimeDataProvider
    lighting: LightingDataProvider
    road: RoadDataProvider
    footfall: FootfallDataProvider
    cctv: CCTVDataProvider
    incidents: IncidentDataProvider
    weather: WeatherDataProvider
    connectivity: ConnectivityDataProvider
    satellite: SatelliteDataProvider
    safe_places: SafePlaceDataProvider
    emergency_infra: EmergencyInfrastructureProvider
    public_transport: PublicTransportProvider
    business: BusinessDataProvider


def build_demo_registry() -> ProviderRegistry:
    """All-simulated wiring: zero external network dependency. Useful for
    offline development and for the automated test suite, where hitting a
    live API on every test run would be slow and flaky."""
    return ProviderRegistry(
        crime=DemoCrimeDataProvider(),
        lighting=DemoLightingDataProvider(),
        road=DemoRoadDataProvider(),
        footfall=DemoFootfallDataProvider(),
        cctv=DemoCCTVDataProvider(),
        incidents=DemoIncidentDataProvider(),
        weather=DemoWeatherDataProvider(),
        connectivity=DemoConnectivityDataProvider(),
        satellite=DemoSatelliteDataProvider(),
        safe_places=DemoSafePlaceDataProvider(),
        emergency_infra=DemoEmergencyInfrastructureProvider(),
        public_transport=DemoPublicTransportProvider(),
        business=DemoBusinessDataProvider(),
    )


def build_real_registry() -> ProviderRegistry:
    """Real-data wiring: road type, street lighting, CCTV camera presence,
    police/hospital/fire proximity, safe places, public transport, and
    activity/footfall density all come from live OpenStreetMap data (free,
    crowdsourced, no API key - see providers/osm.py). Weather comes from
    live Open-Meteo.

    Two categories still have NO free public source of any kind, live or
    otherwise, and are the only ones left on simulated data - each is
    labeled SIMULATED/ESTIMATED in every API response so nothing
    fabricated is ever presented as REAL:
      - crime: no free real-time crime feed exists (would need a paid
        vendor or a government open-data portal specific to one city)
      - connectivity / satellite context: no free real-time network
        coverage map or live satellite analysis API exists
    """
    return ProviderRegistry(
        crime=DemoCrimeDataProvider(),               # no free real-time crime feed available
        lighting=OSMLightingDataProvider(),           # REAL - OpenStreetMap lit=yes / street_lamp tags
        road=OSMRoadDataProvider(),                   # REAL - OpenStreetMap highway= tags
        footfall=OSMActivityDensityProvider(),        # REAL - genuine count of real OSM shops/cafes/restaurants nearby (not a live headcount - see class docstring)
        cctv=OSMCCTVDataProvider(),                   # REAL - OpenStreetMap man_made=surveillance nodes
        incidents=DemoIncidentDataProvider(),         # live incidents come from data/event_bus.py instead
        weather=OpenMeteoWeatherDataProvider(),       # REAL - live Open-Meteo current conditions
        connectivity=DemoConnectivityDataProvider(),  # no free real-time coverage-map API available
        satellite=DemoSatelliteDataProvider(),        # no free real-time satellite analysis API available
        safe_places=OSMSafePlaceDataProvider(),       # REAL - OpenStreetMap pharmacy/fuel/community_centre
        emergency_infra=OSMEmergencyInfrastructureProvider(),  # REAL - OpenStreetMap police/hospital/fire_station
        public_transport=OSMPublicTransportProvider(),  # REAL - OpenStreetMap bus_stop nodes
        business=DemoBusinessDataProvider(),          # no free real-time open/closed status source available
    )


# Module-level singleton used by the API layer. Real data sources (OSM +
# Open-Meteo) require outbound network access - if Guardian is running
# somewhere without internet access, switch this back to
# build_demo_registry() so the app degrades to simulated data instead of
# every request timing out.
DEFAULT_REGISTRY = build_real_registry()
