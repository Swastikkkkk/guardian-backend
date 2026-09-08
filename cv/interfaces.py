"""
Computer Vision model abstraction layer.

CVModel is the pluggable interface. Guardian's scoring engine only ever
consumes CCTVEvent objects (see models/schemas.py) - it never calls a CV
model directly - so any concrete backend (YOLO, OpenCV, MediaPipe, Apple
Vision, a custom PyTorch/TensorFlow model) can be dropped in by
implementing this interface and feeding its output through
cv/event_translator.py.

IMPORTANT SAFETY NOTE: CV outputs become *signals*, never verdicts. A
CVModel implementation must not attempt to identify individuals or assert
criminality; detectEvents() results are things like "unusual activity" or
"possible altercation", scored by confidence, and fed into the safety
score alongside every other signal.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Any, Optional

from models.schemas import CCTVEvent


class CVModel(ABC):
    """Abstract interface every CV backend must implement."""

    @abstractmethod
    def analyze_frame(self, frame: Any, camera_id: str, latitude: float, longitude: float) -> List[CCTVEvent]:
        """Analyze a single image frame and return zero or more CCTVEvents."""
        ...

    @abstractmethod
    def analyze_video(self, video_path: str, camera_id: str, latitude: float, longitude: float) -> List[CCTVEvent]:
        """Analyze a video file/stream and return zero or more CCTVEvents."""
        ...

    def detect_events(self, source: Any, camera_id: str, latitude: float, longitude: float) -> List[CCTVEvent]:
        """Convenience dispatcher: string path -> analyze_video, else analyze_frame."""
        if isinstance(source, str):
            return self.analyze_video(source, camera_id, latitude, longitude)
        return self.analyze_frame(source, camera_id, latitude, longitude)


class NullCVModel(CVModel):
    """No-op model: returns no events. Useful as a safe default wire-up
    before a real CV backend (YOLO/OpenCV/MediaPipe/Vision/custom) is
    connected, and in tests."""

    def analyze_frame(self, frame, camera_id, latitude, longitude) -> List[CCTVEvent]:
        return []

    def analyze_video(self, video_path, camera_id, latitude, longitude) -> List[CCTVEvent]:
        return []


class MockCVModel(CVModel):
    """Deterministic mock used for development/demo before a real model is
    wired in. `scripted_events` lets tests/demos inject specific events."""

    def __init__(self, scripted_events: Optional[List[CCTVEvent]] = None):
        self.scripted_events = scripted_events or []

    def analyze_frame(self, frame, camera_id, latitude, longitude) -> List[CCTVEvent]:
        return [e for e in self.scripted_events if e.camera_id == camera_id]

    def analyze_video(self, video_path, camera_id, latitude, longitude) -> List[CCTVEvent]:
        return [e for e in self.scripted_events if e.camera_id == camera_id]
