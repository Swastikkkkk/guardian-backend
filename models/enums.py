from enum import Enum


class DataLabel(str, Enum):
    """Every value the system emits must be traceable to one of these."""
    REAL = "REAL"
    SIMULATED = "SIMULATED"
    CACHED = "CACHED"
    ESTIMATED = "ESTIMATED"


class RoadType(str, Enum):
    MAIN = "MAIN"
    RESIDENTIAL = "RESIDENTIAL"
    PEDESTRIAN = "PEDESTRIAN"
    HIGHWAY = "HIGHWAY"
    ISOLATED = "ISOLATED"
    UNPAVED = "UNPAVED"
    UNKNOWN = "UNKNOWN"


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    HIGH_RISK = "HIGH_RISK"
    UNKNOWN = "UNKNOWN"


class CVEventType(str, Enum):
    PERSON_DETECTED = "person_detected"
    CROWD_INCREASE = "crowd_increase"
    UNUSUAL_CROWD_BEHAVIOR = "unusual_crowd_behavior"
    RUNNING_OR_CHASING = "running_or_chasing"
    POSSIBLE_ALTERCATION = "possible_altercation"
    FALL = "fall"
    UNUSUAL_MOVEMENT = "unusual_movement"
    ROUTE_OBSTRUCTION = "route_obstruction"
    SUSPICIOUS_PERSISTENT_MOVEMENT = "suspicious_persistent_movement"
    OTHER_ANOMALY = "other_anomaly"


class SafetyEventSource(str, Enum):
    CRIME_REPORT = "crime_report"
    CCTV = "cctv"
    WEATHER = "weather"
    TRAFFIC = "traffic"
    PUBLIC_TRANSPORT = "public_transport"
    CROWD_ACTIVITY = "crowd_activity"
    CONNECTIVITY = "connectivity"
    ENVIRONMENTAL = "environmental"
    USER_REPORT = "user_report"
    SATELLITE = "satellite"


class SafetyEventSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
