# RideIntel Simulation Upgrade — Phase A Baseline Audit

**Date:** 2026-10-12  
**Scope:** Pre-implementation audit of all simulation-related components  

## 1. Map & Visualization

| Aspect | Current State |
|---|---|
| Map library | **Leaflet** (`L.map`, `L.tileLayer`, `L.geoJSON`, `L.circleMarker`) |
| Tile layer | CartoDB dark: `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png` |
| Map center | `[41.85, -87.68]` (Chicago) |
| Zone rendering | **H3 hex polygons** via GeoJSON (`chicagoH3Zones.json`, 239 features) — NOT dots |
| Vehicle markers | `L.circleMarker` — colored circles, not motorcycle icons |
| Vehicle colors | IDLE: `#10b981`, REPOSITION: `#06b6d4`, TO_PICKUP: `#f59e0b`, WITH_PASSENGER: `#8b5cf6`, OFF_DUTY: `#64748b` |
| Route geometry | Straight-line `L.polyline` from origin→target. No road routing. |
| Customer markers | `L.circleMarker` for pickup (emerald) and dropoff (rose) |

## 2. Backend Simulation Engine

| Aspect | Current State |
|---|---|
| Fleet size | 60 deterministic vehicles, seed=42 |
| Zone catalog | 239 zones from `zoneCatalog.json`, 135 forecast-eligible |
| Driver model | Dict with 17 fields incl. lat/lng/status/targets/progress/cooldown |
| Dispatch | Forecast-driven: reads XGBoost predictions, identifies deficit zones, matches idle surplus drivers |
| Origin coverage | Floor of 1 driver — zones with ≤1 idle are protected |
| Destination cap | Max 2 incoming repositioning per zone |
| Cooldown | 6 ticks (3 min equivalent) oscillation prevention |
| Movement | Linear interpolation at 32 km/h between origin/target coords |
| Trip lifecycle | REQUESTED → ASSIGNED → ON_TRIP → COMPLETED / CANCELLED |
| Events system | `self.events` list exists but **no API endpoint exposes it** |
| Post-dropoff re-dispatch | **Not implemented** — driver becomes IDLE but no automatic re-evaluation |

## 3. API Endpoints (13 total)

All return 200 in smoke test:
- `GET /api/v1/health`, `GET /api/v1/metadata`
- `GET /api/v1/forecasts`, `GET /api/v1/pressure`, `GET /api/v1/surge-alerts`, `GET /api/v1/metrics`
- `POST /api/v1/simulation/reset`, `GET /api/v1/simulation/state`
- `POST /api/v1/simulation/dispatch`, `POST /api/v1/simulation/step`
- `GET /api/v1/simulation/trips`
- `POST /api/v1/simulation/customer-requests`, `POST /api/v1/simulation/customer-requests/{id}/cancel`

**Missing:** `GET /api/v1/simulation/events` — events are generated backend-side but never exposed.

## 4. Frontend Components

| File | Purpose |
|---|---|
| `ChicagoMapView.jsx` (1447 lines) | Monolithic map + simulation UI |
| `api.js` (213 lines) | All API calls |
| `chicagoH3Zones.json` (97KB) | 239 H3 polygon GeoJSON |
| `zoneCatalog.json` (41KB) | Zone metadata (lat, lng, label) |
| `zoneLabels.js` | Zone label helpers |
| `simulationFrontend.test.js` | 23 Vitest tests |

## 5. Existing Test Coverage

- **Backend:** 136 passed, 2 skipped (Kafka) across 26 test files
- **Frontend:** 23 passed across 1 test file
- **Immutability:** SHA-256 check of 11 artifacts

## 6. SHA-256 Baseline Hashes (Pre-Upgrade)

```
992a44f66f56f1e5579ddefbe0ec445ff6d705d7e6b8f7ec9a50c1ff6180e7bd  data/processed/forecasts/forecasts.parquet
f7629acd43404ebe551c492dde682ca348891d69af77558e8012f6d925954acb  data/processed/forecasts/forecast_evaluation.parquet
e05844903dc5824e04fe64d376473fcc7308ec4fd5def84abfe6066ff30e5082  data/processed/simulation/surge_alerts.parquet
7600a0cdb27c67b81bb2a6ef92b654f84535213ad02cdb4f2a9980b8295c9f9f  data/processed/simulation/zone_pressure_status.parquet
5fb738d3e99a4db00ee5e1d56b404b3ee75317249eedd7166e06b5f067581970  data/processed/zone_universe/zone_universe.parquet
d80607a641e07968d51af3eb0d85f38966c18381a86bc16ad3615c44ef39fa74  models/xgboost_demand_model.json
```

## 7. Key Gaps Identified for Upgrade

1. **No square grid overlay** — zones are H3 hex polygons (requirement asks for square grid cells)
2. **No motorcycle icons** — vehicles are `L.circleMarker` circles
3. **No road-route geometry** — straight-line interpolation only
4. **No events API endpoint** — `self.events` never exposed to frontend
5. **No event feed from backend** — frontend generates events client-side
6. **No post-dropoff auto re-dispatch** — idle drivers after trip are not re-evaluated
7. **No ON_TRIP/COMPLETED status badges** — trip status display incomplete
8. **WITH_PASSENGER color is violet (#8b5cf6)** — spec requests red
9. **Customer request panel uses H3 cell ID dropdown** — limited to first 40/60 zones
10. **ChicagoMapView is monolithic** — 1447 lines, no component decomposition

