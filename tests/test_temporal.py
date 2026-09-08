from datetime import datetime, timedelta, timezone

from scoring.temporal import (
    crime_recency_weight, incident_recency_weight, time_of_day_bucket, time_of_day_score,
)


def test_crime_decay_recent_higher_than_old():
    now = datetime.now(timezone.utc)
    recent = crime_recency_weight(now - timedelta(days=5), now)
    old = crime_recency_weight(now - timedelta(days=700), now)
    assert recent > old
    assert recent > 0.9
    assert old < 0.1


def test_incident_decay_hours():
    now = datetime.now(timezone.utc)
    fresh = incident_recency_weight(now - timedelta(minutes=2), now)
    stale = incident_recency_weight(now - timedelta(days=14), now)
    assert fresh > 0.95
    assert stale < 0.01
    assert fresh > stale


def test_time_of_day_buckets():
    assert time_of_day_bucket(datetime(2026, 1, 1, 2, 0)) == "early_morning"
    assert time_of_day_bucket(datetime(2026, 1, 1, 8, 0)) == "morning"
    assert time_of_day_bucket(datetime(2026, 1, 1, 13, 0)) == "midday"
    assert time_of_day_bucket(datetime(2026, 1, 1, 18, 0)) == "evening"
    assert time_of_day_bucket(datetime(2026, 1, 1, 21, 0)) == "night"
    assert time_of_day_bucket(datetime(2026, 1, 1, 23, 30)) == "late_night"


def test_time_of_day_score_midday_safer_than_late_night():
    midday = time_of_day_score(datetime(2026, 1, 1, 13, 0))
    late_night = time_of_day_score(datetime(2026, 1, 1, 23, 30))
    assert midday > late_night
