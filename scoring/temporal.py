"""Temporal intelligence: decay functions and time-of-day bucketing.

Safety is not static - the same street can score very differently at
8 AM vs 2 AM. These helpers are the single source of time-based math so
crime decay, incident decay, and hour-of-day weighting stay consistent
across the whole scoring engine.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone

from config.weights import DEFAULT_CONFIG


def _age_in_units(ts: datetime, now: datetime, unit_seconds: float) -> float:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = (now - ts).total_seconds()
    return max(0.0, delta) / unit_seconds


def exponential_decay(age_units: float, half_life_units: float) -> float:
    """Standard half-life decay -> weight in (0, 1]. age=0 -> 1.0."""
    if half_life_units <= 0:
        return 0.0
    return math.pow(0.5, age_units / half_life_units)


def crime_recency_weight(timestamp: datetime, now: datetime) -> float:
    """Older crime records count for less. Uses a half-life in days so a
    record from ~6 months ago (default half-life) carries half the weight
    of a fresh one, and multi-year-old records fade toward negligible -
    avoiding treating historical density as a permanent verdict."""
    age_days = _age_in_units(timestamp, now, 86400.0)
    return exponential_decay(age_days, DEFAULT_CONFIG.temporal.crime_decay_half_life_days)


def incident_recency_weight(timestamp: datetime, now: datetime) -> float:
    """Live incidents/CCTV anomalies decay much faster (hours, not months)."""
    age_hours = _age_in_units(timestamp, now, 3600.0)
    return exponential_decay(age_hours, DEFAULT_CONFIG.temporal.incident_decay_half_life_hours)


def time_of_day_bucket(at_time: datetime) -> str:
    hour = at_time.hour
    if 0 <= hour < 6:
        return "early_morning"
    if 6 <= hour < 11:
        return "morning"
    if 11 <= hour < 16:
        return "midday"
    if 16 <= hour < 20:
        return "evening"
    if 20 <= hour < 23:
        return "night"
    return "late_night"


def time_of_day_risk_multiplier(at_time: datetime) -> float:
    bucket = time_of_day_bucket(at_time)
    return DEFAULT_CONFIG.temporal.hourly_risk_multiplier.get(bucket, 1.0)


def time_of_day_score(at_time: datetime) -> float:
    """0..1 safety-friendly score derived from the risk multiplier
    (inverted and normalized so 1.0 = safest time bucket)."""
    mult = time_of_day_risk_multiplier(at_time)
    all_mults = DEFAULT_CONFIG.temporal.hourly_risk_multiplier.values()
    lo, hi = min(all_mults), max(all_mults)
    if hi == lo:
        return 0.75
    # invert: higher risk multiplier -> lower score
    normalized_risk = (mult - lo) / (hi - lo)
    return round(1.0 - normalized_risk, 3)
