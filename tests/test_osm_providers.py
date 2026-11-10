"""
Tests for the real OSM/Open-Meteo providers. Network calls are mocked so
the suite stays fast and deterministic regardless of whether this machine
can reach overpass-api.de / open-meteo.com - actual live behavior is
verified by running Guardian for real, not by these unit tests.
"""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from models.enums import DataLabel, RoadType
from models.schemas import LatLng
from datetime import datetime as _dt
import providers.osm as _osm
from providers.osm import (
    OSMRoadDataProvider, OSMLightingDataProvider, OSMCCTVDataProvider,
    OSMEmergencyInfrastructureProvider, OSMActivityDensityProvider, _CACHE,
)
from providers.weather_real import OpenMeteoWeatherDataProvider


def _mock_response(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def setup_function():
    _CACHE.clear()  # avoid cross-test cache pollution
    _osm._breaker_tripped_at = None  # a failure test trips the breaker; reset it so later tests reach the mock


def test_osm_road_provider_maps_highway_tag_to_road_type():
    point = LatLng(lat=28.6, lng=77.2)
    fake_data = {"elements": [{"tags": {"highway": "residential"}}]}
    with patch("providers.osm._session.post", return_value=_mock_response(fake_data)):
        result = OSMRoadDataProvider().classify_road(point)
    assert result.value == RoadType.RESIDENTIAL
    assert result.label == DataLabel.REAL


def test_osm_road_provider_no_data_returns_estimated_unknown():
    point = LatLng(lat=0.0, lng=0.0)
    with patch("providers.osm._session.post", return_value=_mock_response({"elements": []})):
        result = OSMRoadDataProvider().classify_road(point)
    assert result.value == RoadType.UNKNOWN
    assert result.label == DataLabel.ESTIMATED


def test_osm_road_provider_network_failure_returns_estimated_not_real():
    point = LatLng(lat=1.0, lng=1.0)
    with patch("providers.osm._session.post", side_effect=Exception("timeout")):
        result = OSMRoadDataProvider().classify_road(point)
    assert result.label == DataLabel.ESTIMATED  # never fabricate REAL on failure


def test_osm_lighting_provider_scores_lit_ways_higher():
    point = LatLng(lat=28.6, lng=77.2)
    fake_data = {"elements": [{"tags": {"lit": "yes"}}, {"tags": {"highway": "street_lamp"}}]}
    with patch("providers.osm._session.post", return_value=_mock_response(fake_data)):
        result = OSMLightingDataProvider().get_lighting_score(point, datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc))
    assert result.label == DataLabel.REAL
    assert result.value > 0.5


def test_osm_cctv_provider_parses_camera_nodes():
    point = LatLng(lat=28.6, lng=77.2)
    fake_data = {"elements": [{"lat": 28.601, "lon": 77.201, "tags": {}}]}
    with patch("providers.osm._session.post", return_value=_mock_response(fake_data)):
        cams = OSMCCTVDataProvider().get_cameras_near(point, 200)
    assert len(cams) == 1
    assert cams[0].label == DataLabel.REAL


def test_osm_emergency_provider_queries_police_amenity():
    point = LatLng(lat=28.6, lng=77.2)
    fake_data = {"elements": [{"lat": 28.601, "lon": 77.201, "tags": {"name": "Sector 12 Police Station"}}]}
    with patch("providers.osm._session.post", return_value=_mock_response(fake_data)):
        stations = OSMEmergencyInfrastructureProvider().get_police_near(point, 1000)
    assert len(stations) == 1
    assert stations[0].name == "Sector 12 Police Station"
    assert stations[0].label == DataLabel.REAL


def test_open_meteo_provider_reduces_score_for_heavy_rain():
    point = LatLng(lat=28.6, lng=77.2)
    fake_json = {"current": {"precipitation": 5.0, "wind_speed_10m": 10}}
    resp = MagicMock()
    resp.json.return_value = fake_json
    resp.raise_for_status.return_value = None
    with patch("providers.weather_real.requests.get", return_value=resp):
        result = OpenMeteoWeatherDataProvider().get_weather_score(point, datetime.now(timezone.utc))
    assert result.label == DataLabel.REAL
    assert result.value < 1.0


def test_open_meteo_provider_network_failure_returns_estimated():
    point = LatLng(lat=28.6, lng=77.2)
    with patch("providers.weather_real.requests.get", side_effect=Exception("timeout")):
        result = OpenMeteoWeatherDataProvider().get_weather_score(point, datetime.now(timezone.utc))
    assert result.label == DataLabel.ESTIMATED


def test_activity_density_provider_uses_real_osm_venue_count():
    point = LatLng(lat=28.6, lng=77.2)
    # Overpass "out count" returns one synthetic element carrying a total.
    fake_data = {"elements": [{"tags": {"total": "9", "nodes": "9", "ways": "0", "relations": "0"}}]}
    with patch("providers.osm._session.post", return_value=_mock_response(fake_data)):
        result = OSMActivityDensityProvider().get_activity_score(point, _dt.now(timezone.utc))
    assert result.label == DataLabel.REAL
    assert result.raw_count == 9
    assert 0.0 <= result.value <= 1.0


def test_activity_density_provider_zero_real_venues_is_a_true_zero_not_a_guess():
    point = LatLng(lat=0.0, lng=0.0)
    fake_data = {"elements": [{"tags": {"total": "0"}}]}
    with patch("providers.osm._session.post", return_value=_mock_response(fake_data)):
        result = OSMActivityDensityProvider().get_activity_score(point, _dt.now(timezone.utc))
    assert result.label == DataLabel.REAL  # a real "nothing mapped here" is still real data, not estimated
    assert result.raw_count == 0
    assert result.value == 0.0


def test_activity_density_provider_network_failure_returns_estimated():
    point = LatLng(lat=28.6, lng=77.2)
    with patch("providers.osm._session.post", side_effect=Exception("timeout")):
        result = OSMActivityDensityProvider().get_activity_score(point, _dt.now(timezone.utc))
    assert result.label == DataLabel.ESTIMATED
    assert result.raw_count is None
