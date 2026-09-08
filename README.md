# Guardian — Geospatial Intelligence & Safe Route Optimization Module

This is the intelligence/data/geospatial **backend** for the Guardian women's
safety platform. It does not build the iPhone UI (a separate SwiftUI app
consumes it) and it does not build the Watch/MyoWare hardware layer. It
consumes geospatial, historical, environmental, real-time, and computer-vision
signals and turns them into structured safety data and safe-route
recommendations, exposed over a clean JSON API.

## Quick start

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
uvicorn api.main:app --reload --port 8000
# open http://localhost:8000/docs for interactive API docs
```

Run the scripted end-to-end hackathon demo (candidate generation → scoring →
live CCTV anomaly → dynamic rerouting):

```bash
python -m simulation.hackathon_demo
```

Run the test suite:

```bash
pytest -q
```

The system runs with **zero external API keys** out of the box: every
provider defaults to a deterministic `Demo*` implementation (see
`providers/demo.py`) labeled `SIMULATED`. Swap in real providers by
implementing the interfaces in `providers/base.py` and wiring them in
`providers/registry.py` — nothing in `scoring/` or `routes/` depends on a
concrete provider.

## Project structure

```
/data          live event bus (in-memory pub/sub + TTL expiry)
/providers     provider interfaces (base.py) + demo implementations + registry
/models        pydantic schemas (the API/JSON contract) + enums
/cv            CVModel abstraction, CCTV event -> SafetyEvent translation
/geospatial    haversine/segmentation math, GeoJSON import/export
/routes        candidate route generation, SafeRouteEngine, dynamic rerouting
/scoring       normalization, temporal decay, segment scoring, route scoring
/simulation    scripted hackathon demo
/api           FastAPI app (all HTTP endpoints)
/config        all tunable weights/thresholds in one place
/tests         pytest suite
```

## Data provenance labeling

Every value the system emits carries a label:

- `REAL` — from a live external API/dataset
- `SIMULATED` — synthetic demo data (current default for all providers)
- `CACHED` — a previously-fetched real value served from cache
- `ESTIMATED` — inferred/derived rather than directly measured

`Sourced` objects (`models/schemas.py`) wrap a value with this label plus a
timestamp, so the API and the iPhone app can always tell what kind of data
backs a given score. `ScoredRoute.label_summary` counts labels used across a
route's segments.

## Safety parameters implemented

Independently normalized to 0..1 before aggregation (`scoring/normalize.py`):
historical crime density (with recency decay), street lighting, time of day,
road type, police proximity, footfall/population/crowd density, CCTV
coverage + live CV anomaly signals, network connectivity, recent/live
incidents, hospital proximity, emergency-service proximity, weather,
satellite/environmental context (flood risk, terrain isolation, vegetation),
road condition, and route isolation. Public transport, safe places, and
nearby open businesses are exposed as POI layers (`/safe-places`,
`get_open_businesses_near`) and are wired into the weighting config
(`config/weights.py`) for use as the platform matures — the initial
aggregate score focuses on the parameters proven out in `scoring/segment_scoring.py`,
and every additional weight already has a named slot ready to receive a
real signal.

All weights live in `config/weights.py` (`ParameterWeights`,
`RoadTypeWeights`, `TemporalConfig`, `ScoringThresholds`) — nothing is
hard-coded inline in the scoring engine, and this is the file to replace
with ML-learned weights later.

## Route segmentation

Routes are never scored as one number. `geospatial/utils.split_into_segments`
breaks every candidate route into ~250m segments (configurable); each segment
gets its own full `SegmentScoreBreakdown`, `overall_safety_score`,
`risk_level`, `confidence`, and explicit `positive_factors` /
`negative_factors`. `scoring/route_scoring.score_route` aggregates segments
into a route-level score using a distance-weighted mean, and surfaces the
worst segments' negative factors even when the overall route looks safe.

## Explainability

No score is ever returned bare. Every `RouteSegment` and `ScoredRoute`
carries `positive_factors` / `negative_factors` as human-readable strings
(e.g. "Strong CCTV coverage", "Recent CCTV anomaly detected nearby"), plus a
`confidence` value reflecting how much of the weighted signal set was
actually backed by available data (`scoring/normalize.weighted_mean`) rather
than silently defaulting to a fabricated score.

## Computer vision integration

`cv/interfaces.py` defines the `CVModel` abstraction (`analyze_frame`,
`analyze_video`, `detect_events`) so any backend (YOLO, OpenCV, MediaPipe,
Apple Vision, a custom PyTorch/TensorFlow model) can be plugged in without
touching the scoring engine — the engine only ever consumes the resulting
`CCTVEvent` objects. Event types are restricted to anomaly/behavior
descriptions ("possible altercation", "unusual activity", "possible route
obstruction", etc.) — never identity or criminality claims; `CCTVEvent`'s
pydantic validator actively rejects description text that asserts a
person's criminal identity. CV events are translated into the unified
`SafetyEvent` pipeline (`cv/event_translator.py`) with severity-based
confidence impact and TTL, so a detected anomaly decays out of the live
score over hours, not permanently.

## Live data pipeline & dynamic rerouting

`data/event_bus.py` is a lightweight in-memory pub/sub store (swap for
Kafka/Redis/Postgres later behind the same interface) that normalizes every
live signal into a `SafetyEvent` with automatic TTL expiry — a two-week-old
incident is never treated like a two-minute-old one. `POST /events` and
`POST /events/cctv` ingest new signals; `routes/safe_route_engine.py`'s
`dynamic_reroute()` re-scores the active route against current live data and
returns a `DynamicRouteUpdate` (previous score, new score, reason,
recommendation, alternative route) whenever a materially safer route has
emerged (delta threshold configurable in `config/weights.py`).

## GeoJSON

`geospatial/geojson_utils.py` provides `Point` / `LineString` / `Polygon` /
`FeatureCollection` builders and exporters for every domain object (route
segments, crime records, safety events, CCTV events, POIs). Any endpoint
that returns spatial data accepts `?as_geojson=true` to get a standard
`FeatureCollection` instead of raw JSON records.

## API for the iPhone app

| Endpoint | Purpose |
|---|---|
| `POST /route/safe` | Core: origin/destination(/time) → recommended + alternative scored routes |
| `GET /route/{id}` | Fetch a previously computed scored route |
| `GET /route/{id}/segments` | Per-segment breakdown (optionally GeoJSON) |
| `POST /route/{id}/check-reroute` | Poll during an active journey for a `DynamicRouteUpdate` |
| `GET /safety/area` | Safety score for a single point/area |
| `GET /safety/nearby` | Everything known near a point (incidents, CCTV, POIs) |
| `GET /incidents` | Live incidents near a point |
| `GET /cctv/events` | Recent CCTV anomaly events near a point |
| `GET /safe-places` | Safe-place POIs near a point |
| `GET /environment` | Weather + satellite context + connectivity for a point |
| `POST /events` | Ingest a generic live `SafetyEvent` |
| `POST /events/cctv` | Ingest a `CCTVEvent` from a CV model |

Example `POST /route/safe` response shape:

```json
{
  "recommended_route": {
    "id": "route_...",
    "overall_safety_score": 87.3,
    "risk_level": "SAFE",
    "confidence": 0.91,
    "estimated_duration_s": 1080,
    "positive_factors": ["Strong CCTV coverage", "High public activity / footfall"],
    "negative_factors": ["Poor street lighting"],
    "segments": [ { "overall_safety_score": 92.1, "risk_level": "SAFE", "...": "..." } ]
  },
  "alternative_routes": ["..."],
  "all_routes_ranked": ["route_a", "route_b", "route_c"]
}
```

Full field-level schemas are in `models/schemas.py` and live interactive
docs are at `/docs` when the server is running.

## Real vs demo mode & external data sources

The system ships in **demo mode**: every provider in `providers/demo.py`
generates deterministic synthetic data seeded by location, labeled
`SIMULATED`. To move a provider to production, implement the matching
interface in `providers/base.py` against a real source and swap it in
`providers/registry.py`. Suggested real sources per provider (not
integrated here — verify licensing/ToS before use in production):

- **CrimeDataProvider**: national/state open crime data portals (e.g.
  India's NCRB open data, or a city police open-data API) — check dataset
  license and update cadence.
- **LightingDataProvider**: municipal streetlight GIS layers where published;
  otherwise inferred from OSM `lit=yes` tags (OpenStreetMap, ODbL license).
- **RoadDataProvider**: OpenStreetMap road classification (ODbL) or a
  commercial routing API (Google Roads, Mapbox — each has its own ToS/pricing).
- **FootfallDataProvider**: telecom/aggregator footfall products, or transit
  ridership open data; must be aggregated/anonymized per the privacy section
  below.
- **CCTVDataProvider / CV models**: municipal smart-city camera feeds (where
  legally accessible) processed by a locally-run CV model — never a
  third-party facial-recognition API.
- **WeatherDataProvider**: IMD (India Meteorological Department) or
  OpenWeatherMap (commercial API key required).
- **ConnectivityDataProvider**: OpenCellID / carrier coverage maps.
- **SatelliteDataProvider**: Sentinel Hub / Copernicus (free tier, ESA terms)
  or Google Earth Engine (usage terms apply).
- **SafePlaceDataProvider / EmergencyInfrastructureProvider /
  PublicTransportProvider / BusinessDataProvider**: OpenStreetMap POIs
  (ODbL) or Google Places API (commercial, ToS restricts caching raw data).

Whatever is integrated, keep the `DataLabel` on every value honest —
never present a `SIMULATED` or `ESTIMATED` value as `REAL`.

## Privacy

Anonymized device/activity density is treated as one aggregated
environmental signal only (`FootfallDataProvider`), never as raw per-device
data, and the module never stores unnecessary PII. `CCTVEvent` never encodes
personal identity — see the CV section above.
