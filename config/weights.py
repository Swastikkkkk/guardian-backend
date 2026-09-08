"""
Central, single-source-of-truth configuration for Guardian's scoring engine.

Nothing in /scoring or /routes should hard-code a weight or threshold.
Everything tunable lives here so it can later be swapped for ML-learned
weights without touching engine code.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict


@dataclass
class ParameterWeights:
    """Relative importance of each normalized (0..1) safety signal.

    Weights do not need to sum to 1 - the scoring engine normalizes the
    weighted sum by the sum of weights actually available for a given
    segment (see scoring/segment_scoring.py: missing-data handling).
    """
    crime: float = 0.16
    lighting: float = 0.12
    time_of_day: float = 0.06
    road_type: float = 0.08
    police_proximity: float = 0.08
    footfall: float = 0.08
    cctv: float = 0.09
    connectivity: float = 0.05
    incidents: float = 0.10
    hospital_proximity: float = 0.03
    emergency_proximity: float = 0.03
    public_transport: float = 0.03
    nearby_businesses: float = 0.02
    safe_places: float = 0.04
    crowd_density: float = 0.03
    device_density: float = 0.02
    weather: float = 0.02
    environmental: float = 0.02
    road_condition: float = 0.02
    isolation: float = 0.05
    cv_anomaly: float = 0.10
    reported_incidents_live: float = 0.07

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class RoadTypeWeights:
    """Base safety multipliers by road classification (0..1).

    These are *priors*, not verdicts - "isolated" roads are not
    automatically unsafe, they simply start from a more cautious prior
    that other signals (lighting, footfall, CCTV) can raise or confirm.
    """
    MAIN: float = 0.75
    RESIDENTIAL: float = 0.65
    PEDESTRIAN: float = 0.60
    HIGHWAY: float = 0.55
    ISOLATED: float = 0.35
    UNPAVED: float = 0.40
    UNKNOWN: float = 0.50


@dataclass
class TemporalConfig:
    """Controls for time-of-day / decay based scoring."""
    # Multiplier applied to the "risk" component of a score by hour bucket.
    # 1.0 = neutral, >1.0 = riskier, <1.0 = safer.
    hourly_risk_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "early_morning": 1.15,   # 00:00-05:59
        "morning": 0.85,         # 06:00-10:59
        "midday": 0.80,          # 11:00-15:59
        "evening": 1.00,         # 16:00-19:59
        "night": 1.25,           # 20:00-22:59
        "late_night": 1.40,      # 23:00-23:59
    })
    # Half-life (in days) for historical crime record decay.
    crime_decay_half_life_days: float = 180.0
    # Half-life (in hours) for live incident / CCTV event decay.
    incident_decay_half_life_hours: float = 48.0
    # Default time-to-live (hours) for a live SafetyEvent lacking one.
    default_event_ttl_hours: float = 72.0


@dataclass
class ScoringThresholds:
    safe_min: float = 75.0        # score >= this -> SAFE
    caution_min: float = 50.0     # score >= this -> CAUTION, else HIGH_RISK
    unknown_confidence_min: float = 0.25  # below this data confidence -> UNKNOWN


@dataclass
class EngineConfig:
    weights: ParameterWeights = field(default_factory=ParameterWeights)
    road_type_weights: RoadTypeWeights = field(default_factory=RoadTypeWeights)
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)
    segment_target_length_m: float = 250.0
    max_alternative_routes: int = 3
    rerouting_score_delta_trigger: float = 1.5  # points; new info must swing score by this much to trigger reroute suggestion


DEFAULT_CONFIG = EngineConfig()
