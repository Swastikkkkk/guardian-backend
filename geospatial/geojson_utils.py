"""Reusable GeoJSON import/export helpers.

Every geospatial thing Guardian produces (routes, segments, incidents,
zones, cameras, police stations, hospitals, safe places, lighting,
mesh nodes, environmental regions) can be round-tripped through these
functions so the iPhone app / any map SDK gets standard GeoJSON.
"""
from __future__ import annotations
from typing import List, Dict, Any, Iterable

from models.schemas import (
    LatLng, GeoJSONFeature, GeoJSONGeometry, GeoJSONFeatureCollection,
    RouteSegment, PointOfInterest, CrimeRecord, SafetyEvent, CCTVEvent,
)


def point_feature(point: LatLng, properties: Dict[str, Any], feature_id: str = None) -> GeoJSONFeature:
    return GeoJSONFeature(
        geometry=GeoJSONGeometry(type="Point", coordinates=point.as_geojson_coord()),
        properties=properties,
        id=feature_id,
    )


def linestring_feature(points: List[LatLng], properties: Dict[str, Any], feature_id: str = None) -> GeoJSONFeature:
    return GeoJSONFeature(
        geometry=GeoJSONGeometry(type="LineString", coordinates=[p.as_geojson_coord() for p in points]),
        properties=properties,
        id=feature_id,
    )


def polygon_feature(rings: List[List[LatLng]], properties: Dict[str, Any], feature_id: str = None) -> GeoJSONFeature:
    coords = [[p.as_geojson_coord() for p in ring] for ring in rings]
    return GeoJSONFeature(
        geometry=GeoJSONGeometry(type="Polygon", coordinates=coords),
        properties=properties,
        id=feature_id,
    )


def feature_collection(features: Iterable[GeoJSONFeature]) -> GeoJSONFeatureCollection:
    return GeoJSONFeatureCollection(features=list(features))


# --- Domain-object convenience exporters -----------------------------------

def route_segment_to_feature(segment: RouteSegment) -> GeoJSONFeature:
    props = {
        "segment_id": segment.id,
        "sequence_index": segment.sequence_index,
        "road_type": segment.road_type.value,
        "overall_safety_score": segment.overall_safety_score,
        "risk_level": segment.risk_level.value,
        "confidence": segment.confidence,
        "positive_factors": segment.positive_factors,
        "negative_factors": segment.negative_factors,
        "distance_m": segment.distance_m,
    }
    return linestring_feature(segment.geometry, props, feature_id=segment.id)


def poi_to_feature(poi: PointOfInterest) -> GeoJSONFeature:
    return point_feature(
        LatLng(lat=poi.latitude, lng=poi.longitude),
        {"id": poi.id, "type": poi.type, "name": poi.name, "label": poi.label.value, **poi.metadata},
        feature_id=poi.id,
    )


def crime_record_to_feature(rec: CrimeRecord) -> GeoJSONFeature:
    if rec.polygon:
        ring = [LatLng(lat=lat, lng=lng) for lat, lng in rec.polygon]
        return polygon_feature([ring], {
            "id": rec.id, "category": rec.category, "severity": rec.severity,
            "timestamp": rec.timestamp.isoformat(), "label": rec.label.value,
        }, feature_id=rec.id)
    return point_feature(
        LatLng(lat=rec.latitude, lng=rec.longitude),
        {"id": rec.id, "category": rec.category, "severity": rec.severity,
         "timestamp": rec.timestamp.isoformat(), "label": rec.label.value},
        feature_id=rec.id,
    )


def safety_event_to_feature(evt: SafetyEvent) -> GeoJSONFeature:
    return point_feature(
        evt.location,
        {
            "id": evt.id, "source": evt.source.value, "type": evt.type,
            "severity": evt.severity.value, "confidence": evt.confidence,
            "timestamp": evt.timestamp.isoformat(),
            "expires_at": evt.expires_at.isoformat() if evt.expires_at else None,
            "label": evt.label.value,
        },
        feature_id=evt.id,
    )


def cctv_event_to_feature(evt: CCTVEvent) -> GeoJSONFeature:
    return point_feature(
        LatLng(lat=evt.latitude, lng=evt.longitude),
        {
            "id": evt.id, "camera_id": evt.camera_id, "event_type": evt.event_type.value,
            "confidence": evt.confidence, "severity": evt.severity.value,
            "timestamp": evt.timestamp.isoformat(), "label": evt.label.value,
        },
        feature_id=evt.id,
    )
