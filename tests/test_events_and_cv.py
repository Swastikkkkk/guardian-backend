from datetime import datetime, timedelta, timezone

from models.enums import CVEventType, SafetyEventSeverity, SafetyEventSource, DataLabel
from models.schemas import LatLng, CCTVEvent, SafetyEvent
from data.event_bus import LiveEventBus
from cv.event_translator import cctv_event_to_safety_event, cv_anomaly_impact
from cv.interfaces import NullCVModel, MockCVModel


def test_event_expires_after_ttl():
    bus = LiveEventBus()
    now = datetime.now(timezone.utc)
    evt = SafetyEvent(
        location=LatLng(lat=1, lng=1), source=SafetyEventSource.USER_REPORT, type="test",
        severity=SafetyEventSeverity.LOW, confidence=0.9,
        timestamp=now - timedelta(hours=100), expires_at=now - timedelta(hours=1),
    )
    bus.publish(evt)
    active = bus.query_near(LatLng(lat=1, lng=1), 1000, now=now)
    assert evt.id not in [e.id for e in active]


def test_event_default_ttl_applied_when_missing():
    bus = LiveEventBus()
    evt = SafetyEvent(
        location=LatLng(lat=2, lng=2), source=SafetyEventSource.TRAFFIC, type="jam",
        severity=SafetyEventSeverity.LOW, confidence=0.5,
    )
    published = bus.publish(evt)
    assert published.expires_at is not None
    assert published.expires_at > published.timestamp


def test_cctv_event_translates_to_safety_event_with_ttl_by_severity():
    evt = CCTVEvent(
        camera_id="cam1", latitude=1.0, longitude=1.0,
        event_type=CVEventType.POSSIBLE_ALTERCATION, confidence=0.9,
        severity=SafetyEventSeverity.HIGH,
    )
    safety_evt = cctv_event_to_safety_event(evt)
    assert safety_evt.source == SafetyEventSource.CCTV
    assert safety_evt.expires_at > safety_evt.timestamp
    assert cv_anomaly_impact(evt) > 0.3


def test_cctv_event_rejects_identity_claims():
    import pytest
    with pytest.raises(Exception):
        CCTVEvent(
            camera_id="cam1", latitude=1.0, longitude=1.0,
            event_type=CVEventType.OTHER_ANOMALY, confidence=0.5,
            severity=SafetyEventSeverity.LOW,
            description="the thief is wearing a red jacket",
        )


def test_null_cv_model_returns_no_events():
    model = NullCVModel()
    assert model.detect_events("some/video.mp4", "cam1", 1.0, 1.0) == []


def test_mock_cv_model_returns_scripted_events_for_matching_camera():
    scripted = [CCTVEvent(
        camera_id="cam1", latitude=1.0, longitude=1.0,
        event_type=CVEventType.FALL, confidence=0.7, severity=SafetyEventSeverity.MEDIUM,
    )]
    model = MockCVModel(scripted_events=scripted)
    events = model.detect_events("frame_bytes", "cam1", 1.0, 1.0)
    assert len(events) == 1
    assert model.detect_events("frame_bytes", "cam2", 1.0, 1.0) == []
