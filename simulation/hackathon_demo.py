"""
Scripted end-to-end demo matching the hackathon walkthrough in the module
brief:

  1. Select A -> B
  2. Generate candidate routes
  3. Score every route
  4. Show individual factors
  5. Pick safest practical route
  6. User starts journey
  7. New CCTV anomaly appears on the chosen route
  8. A recent incident appears on the chosen route
  9. Safety score changes
  10. System recalculates
  11. A safer alternative becomes available
  12. Return the updated route (DynamicRouteUpdate) to the app

Run directly: `python -m simulation.hackathon_demo`
"""
from __future__ import annotations
from datetime import datetime, timezone

from models.enums import CVEventType, SafetyEventSeverity, SafetyEventSource, DataLabel
from models.schemas import LatLng, CCTVEvent, SafetyEvent
from routes.safe_route_engine import ENGINE
from data.event_bus import EVENT_BUS
from cv.event_translator import cctv_event_to_safety_event


def run():
    origin = LatLng(lat=28.5700, lng=77.3200)       # Sector 62-ish, Noida (demo coords)
    destination = LatLng(lat=28.5810, lng=77.3310)
    now = datetime.now(timezone.utc)

    print("=" * 70)
    print("STEP 1-4: generating and scoring candidate routes")
    print("=" * 70)
    result = ENGINE.plan(origin, destination, at_time=now, max_alternatives=2)
    for r in [result.recommended_route, *result.alternative_routes]:
        mins = r.estimated_duration_s / 60
        print(f"\nRoute {r.id} ({r.risk_level.value})  {mins:.0f} min  Safety Score: {r.overall_safety_score}")
        print(f"  + {', '.join(r.positive_factors) or 'no standout positives'}")
        print(f"  - {', '.join(r.negative_factors) or 'no major concerns'}")

    print("\n" + "=" * 70)
    print("STEP 5-6: safest practical route selected, journey starts")
    print("=" * 70)
    chosen = result.recommended_route
    print(f"Chosen route: {chosen.id} (score {chosen.overall_safety_score})")

    print("\n" + "=" * 70)
    print("STEP 7: new CCTV anomaly appears on the chosen route")
    print("=" * 70)
    mid_segment = chosen.segments[len(chosen.segments) // 2]
    anomaly_point = mid_segment.geometry[len(mid_segment.geometry) // 2]
    cctv_evt = CCTVEvent(
        camera_id="CAM-DEMO-1", latitude=anomaly_point.lat, longitude=anomaly_point.lng,
        event_type=CVEventType.POSSIBLE_ALTERCATION, confidence=0.82,
        severity=SafetyEventSeverity.HIGH, label=DataLabel.SIMULATED,
        description="Unusual activity flagged by CV model",
    )
    EVENT_BUS.publish_cctv_event(cctv_evt)
    EVENT_BUS.publish(cctv_event_to_safety_event(cctv_evt))
    print(f"Published CCTV anomaly at {anomaly_point} on segment {mid_segment.id}")

    print("\n" + "=" * 70)
    print("STEP 8: a recent incident is reported on the same route")
    print("=" * 70)
    incident = SafetyEvent(
        location=anomaly_point, source=SafetyEventSource.USER_REPORT, type="harassment_report",
        severity=SafetyEventSeverity.HIGH, confidence=0.75, label=DataLabel.SIMULATED,
    )
    EVENT_BUS.publish(incident)
    print(f"Published incident {incident.id} near the same segment")

    print("\n" + "=" * 70)
    print("STEP 9-11: recalculating - checking for a safer alternative")
    print("=" * 70)
    update = ENGINE.dynamic_reroute(
        chosen.id, origin, destination, at_time=now,
        triggering_event_ids=[cctv_evt.id, incident.id],
    )
    if update:
        print(f"DynamicRouteUpdate: {update.reason}")
        print(f"  previous_score={update.previous_score}  new_score={update.new_score}")
        print(f"  recommendation: {update.recommendation}")
        print(f"  alternative route: {update.alternative_route.id} (score {update.alternative_route.overall_safety_score})")
    else:
        print("No materially safer alternative found (try re-running - demo data is randomized per-location).")

    print("\n" + "=" * 70)
    print("STEP 12: this DynamicRouteUpdate JSON is what gets pushed to the iPhone app")
    print("=" * 70)
    if update:
        print(update.model_dump_json(indent=2)[:2000], "... (truncated)")


if __name__ == "__main__":
    run()
