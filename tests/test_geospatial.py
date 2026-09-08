from models.schemas import LatLng
from geospatial.utils import haversine_m, split_into_segments, polyline_length_m, bounding_box
from geospatial.geojson_utils import linestring_feature, point_feature, feature_collection


def test_haversine_known_distance():
    # Roughly 1 degree of latitude ~ 111.2 km
    a = LatLng(lat=0.0, lng=0.0)
    b = LatLng(lat=1.0, lng=0.0)
    d = haversine_m(a, b)
    assert 110_000 < d < 112_000


def test_split_into_segments_covers_full_length():
    points = [LatLng(lat=0.0, lng=0.0 + i * 0.001) for i in range(20)]
    total = polyline_length_m(points)
    segments = split_into_segments(points, target_length_m=200)
    assert len(segments) >= 1
    reconstructed = sum(polyline_length_m(s) for s in segments)
    assert abs(reconstructed - total) < 5.0  # meters tolerance


def test_split_into_segments_handles_short_route():
    points = [LatLng(lat=0.0, lng=0.0), LatLng(lat=0.0001, lng=0.0001)]
    segments = split_into_segments(points, target_length_m=250)
    assert len(segments) == 1


def test_bounding_box():
    points = [LatLng(lat=1.0, lng=1.0), LatLng(lat=2.0, lng=2.0)]
    min_lat, min_lng, max_lat, max_lng = bounding_box(points)
    assert min_lat <= 1.0 and max_lat >= 2.0
    assert min_lng <= 1.0 and max_lng >= 2.0


def test_geojson_feature_collection_roundtrip():
    pt = point_feature(LatLng(lat=1.0, lng=2.0), {"name": "test"})
    line = linestring_feature([LatLng(lat=0, lng=0), LatLng(lat=1, lng=1)], {"id": "x"})
    fc = feature_collection([pt, line])
    assert fc.type == "FeatureCollection"
    assert len(fc.features) == 2
    assert fc.features[0].geometry.type == "Point"
    assert fc.features[1].geometry.type == "LineString"
