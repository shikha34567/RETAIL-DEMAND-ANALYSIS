# RideIntel Fleet Simulation Command Centre — Phase 1 Report
## Interactive Chicago Map, H3 Polygon Heatmap & Real Forecast Integration

**Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand & Supply Intelligence System  
**Phase:** Fleet Simulation Command Centre — Phase 1 (Repository Audit, Interactive Chicago Map & Forecast Heatmap)  
**Author:** Lead Full-Stack & ML Systems Engineer (Antigravity)  
**Status:** Complete  
**Final Verdict:** **PASS WITH LIMITATIONS** (All offline frontend and backend test suites passing; 11 canonical Phase 1–4 artifacts strictly invariant; live Kafka broker and interactive browser drivers unavailable on host)

---

## Executive Summary

Phase 1 of the Fleet Simulation Command Centre delivers an interactive geographic visualization of the Chicago operating area, rendering actual Resolution 8 H3 hexagonal polygons derived directly from project spatial coordinates using Uber's official `h3-py` library. The map seamlessly integrates with the existing FastAPI backend to display real XGBoost predicted demand, simulated vehicle supply, and demand-supply pressure metrics.

All existing analytics dashboards (Overview, Zone Intelligence, Model Performance, Surge Alerts, and System Governance), API contracts in `contracts/`, and immutable Phase 1–4 historical Parquet artifacts were strictly preserved without modification.

---

## 1. Repository Audit & Stack Architecture

Prior to development, the repository was audited:
1. **Frontend Architecture:**
   - Stack: React 19.2.8 + Vite 8.3.0 + TailwindCSS 4.3.3 + Lucide Icons + Recharts.
   - Dashboards: Existing modular view architecture with tabbed routing managed in `App.jsx`.
   - APIs: Axios-based client in `frontend/src/services/api.js` pointing to `/api/v1` via Vite dev proxy (`localhost:8000`).
2. **Backend API Contracts:**
   - FastAPI server exposing `/health`, `/metadata`, `/forecasts`, `/pressure`, `/surge-alerts`, and `/metrics`.
   - Strict adherence to `contracts/parquet_schemas.md` and `contracts/openapi.yaml`.
3. **Spatial Data Assets:**
   - `data/processed/zone_universe/zone_universe.parquet`: 239 total catalog cells at H3 Resolution 8, of which 135 are operational test-forecast zones.
   - Initial frontend catalog `zoneCatalog.json` contained centroids, but lacked polygon boundary vertices for SVG/Canvas/GIS rendering.

---

## 2. Dependencies Added

| Package | Version | Purpose & Rationale |
| :--- | :---: | :--- |
| `leaflet` | `^1.9.4` | Lightweight (~140 kB), robust map rendering engine with built-in GeoJSON support, high-performance vector rendering, dark tile compatibility, and zero peer-dependency conflicts with React 19. |

*Note: No other dependencies or backend libraries were added. `leaflet` was installed via npm and configured with custom dark-matter styles in `index.css`.*

---

## 3. Spatial Geometry & H3 Polygon Generation

### 3.1 Geometry Extraction
To guarantee that the map renders **actual H3 hexagonal zone polygons** rather than bounding boxes, approximate circles, or arbitrary shapes:
1. Sourced all 239 Resolution 8 cells from `zone_universe.parquet`.
2. Extracted exact boundary vertices for each cell using `h3.cell_to_boundary(cell)` (6 geographic coordinates).
3. Converted into closed GeoJSON Polygon coordinates (`[ [ [lng, lat], ..., [lng0, lat0] ] ]`) with coordinates rounded to 6 decimal places (~0.1m precision).
4. Persisted as [`frontend/src/services/chicagoH3Zones.json`](file:///c:/Users/91984/OneDrive/Desktop/ride demand analysis -- intel/frontend/src/services/chicagoH3Zones.json).

### 3.2 Verification
- Every polygon ring contains exactly 7 coordinates (6 hex vertices + 1 closing coordinate).
- All coordinates lie within the Chicago metropolitan bounding box ($41.60 \le \text{lat} \le 42.10$, $-87.95 \le \text{lng} \le -87.50$).
- Validated via unit test suite `frontend/test/mapGeoJSON.test.js`.

---

## 4. Map & Forecast Functionality Implemented

### 4.1 Interactive Map Component (`ChicagoMapView.jsx`)
- **Map Viewport:** Centered on Chicago metropolitan area (`[41.85, -87.68]`), initial zoom level 11, with `fitBounds` capability to frame all 239 zones.
- **Base Map Tiles:** CartoDB Dark Matter tiles (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`) matching the dark slate design system (`#020617`, `#0B0F19`, `#1E293B`).
- **Demand Heatmap Layer:** Choropleth heatmap dynamically colored by real XGBoost **PREDICTED** demand ($D$ in rides/30m):
  - Tier 1: $< 0.1$ rides &rarr; `#334155` (Slate / Trace)
  - Tier 2: $0.1 – 1.0$ rides &rarr; `#0284c7` (Sky Blue / Low)
  - Tier 3: $1.0 – 5.0$ rides &rarr; `#06b6d4` (Cyan / Moderate)
  - Tier 4: $5.0 – 15.0$ rides &rarr; `#10b981` (Emerald / Elevated)
  - Tier 5: $15.0 – 35.0$ rides &rarr; `#f59e0b` (Amber / High)
  - Tier 6: $> 35.0$ rides &rarr; `#f43f5e` (Rose / Surge Core)
- **Map Controls:**
  - **Heatmap Toggle:** Enables/disables demand color fill.
  - **Boundaries Toggle:** Enables/disables hex polygon stroke outlines.
  - **Center View:** Refocuses Chicago metropolitan area.
  - **Heatmap Legend:** Explains color swatches and units (rides / 30m).

### 4.2 Forecast & Telemetry Integration
- **Origin Snapshot Selector:** Allows toggling between test-set forecast origins (Jun 22 Midnight baseline, Jun 22 Morning Commute peak, Jun 22 Midday peak, Jun 22 Evening rush, Jun 23 Midday peak, Jun 24 Weekend night, Jun 30 Month-end peak).
- **Snapshot Metadata Ribbon:** Displays local origin time (America/Chicago), next-30-minute prediction horizon (`target_start` to `target_end`), total snapshot demand, total simulated capacity, and number of shortage zones.
- **Refresh Forecast Button:** Re-queries API for the active snapshot origin without reloading the page.
- **Interactive Inspection Panel:** Clicking any zone reveals:
  - Canonical label (`Zone Z-XXX`) and raw H3 Hex ID with one-click copy.
  - Centroid coordinates (lat, lng) and H3 Resolution 8 designation.
  - Predicted Demand $D$ (rides / 30m).
  - Estimated Capacity $C$ and available vehicles $V$.
  - Expected Shortage $\max(0, D - C)$ in rides.
  - Pressure Level badge (`LOW`, `MODERATE`, `HIGH`, `CRITICAL`, `NO_CAPACITY`).
  - Active surge alert notice (if flagged).
  - Deep-link button to Zone Intelligence view.

---

## 5. Verification Results

### 5.1 Frontend Unit Tests (`npm test`)
```text
> frontend@0.0.0 test
> node --test test/*.test.js

✔ formatChicagoTime converts UTC to Chicago Daylight Time (CDT) (73.9427ms)
✔ formatChicagoTimeOnly formats time portion in America/Chicago (1.2623ms)
✔ formatChicagoTime handles empty, null and invalid inputs gracefully (0.2755ms)
✔ ApiError preserves HTTP status and payload detail (1.5882ms)
✔ chicagoH3Zones.json contains exactly 239 Resolution 8 features (1.7838ms)
✔ every feature in chicagoH3Zones has valid geometry and closed polygon ring (5.1739ms)
✔ every feature in chicagoH3Zones has canonical properties matching zone catalog (0.7417ms)
✔ heatmap tier thresholds map demand accurately (0.2483ms)
✔ Overview chart data transformation preserves fractional predicted demand for Zone Z-005 (2.9826ms)
✔ Overview shortage sort correctly prioritizes NO_CAPACITY deficits over surplus zones (0.4667ms)
✔ getZoneLabel returns deterministic friendly label for known cell (1.5506ms)
✔ getZoneLabel handles null, undefined and unknown gracefully (0.2612ms)
✔ getZoneDetails returns valid coordinates and resolution (0.3341ms)
✔ getAllZoneLabels returns all 239 catalog entries sorted (0.31ms)
ℹ tests 14
ℹ suites 0
ℹ pass 14
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 215.1975
```

### 5.2 Frontend Production Build (`npm run build`)
```text
> frontend@0.0.0 build
> vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 2497 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                 0.78 kB │ gzip:   0.37 kB
dist/assets/index-BsPSh06Y.css                 62.84 kB │ gzip:  14.93 kB
dist/assets/rolldown-runtime-hePW80VL.js        0.71 kB │ gzip:   0.42 kB
dist/assets/api-c7chiWEW.js                     4.49 kB │ gzip:   1.96 kB
dist/assets/SurgeAlertsView-6980-om-.js         6.52 kB │ gzip:   2.11 kB
dist/assets/ZoneIntelligenceView-DD5Ez736.js    8.52 kB │ gzip:   2.62 kB
dist/assets/ModelPerformanceView-B8RIHPPf.js    9.75 kB │ gzip:   2.47 kB
dist/assets/vendor-icons-C1BbOiCt.js           10.87 kB │ gzip:   4.19 kB
dist/assets/SystemStatusView-CSHTyOlh.js       12.61 kB │ gzip:   3.14 kB
dist/assets/ChicagoMapView-Bx-KMoeH.js        249.42 kB │ gzip:  65.23 kB
dist/assets/index-YBZz1nYZ.js                 265.55 kB │ gzip:  79.36 kB
dist/assets/vendor-charts-DdmkzTbP.js         382.05 kB │ gzip: 110.15 kB

✓ built in 1.27s
```

### 5.3 Backend Pytest Suite (`python -m pytest`)
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2
collected 121 items

tests\integration\test_streaming_pipeline.py ss                          [  1%]
tests\unit\test_api_forecasts.py .........                               [  9%]
tests\unit\test_api_health.py ....                                       [ 12%]
tests\unit\test_api_immutability.py .                                    [ 13%]
tests\unit\test_api_metrics.py ....                                      [ 16%]
tests\unit\test_api_pressure.py ..........                               [ 24%]
tests\unit\test_api_surge.py ......                                      [ 29%]
tests\unit\test_clean_pipeline.py ......                                 [ 34%]
tests\unit\test_cleaning_policy.py ........                              [ 41%]
tests\unit\test_forecasting_aggregation.py ......                        [ 46%]
tests\unit\test_forecasting_baselines.py ..                              [ 47%]
tests\unit\test_forecasting_evaluate.py ...                              [ 50%]
tests\unit\test_forecasting_features.py ...                              [ 52%]
tests\unit\test_forecasting_model.py ..                                  [ 54%]
tests\unit\test_forecasting_pipeline_job.py .                            [ 55%]
tests\unit\test_h3_comparison.py ....                                    [ 58%]
tests\unit\test_h3_index.py .......                                      [ 64%]
tests\unit\test_phase4_pipeline_job.py .                                 [ 65%]
tests\unit\test_pressure_and_surge.py .....                              [ 69%]
tests\unit\test_profile_raw.py ......                                    [ 74%]
tests\unit\test_streaming_consumer.py .....                              [ 78%]
tests\unit\test_streaming_contract.py ...........                        [ 87%]
tests\unit\test_streaming_producer.py ...                                [ 90%]
tests\unit\test_supply_simulation.py ...                                 [ 92%]
tests\unit\test_zone_universe.py .........                               [100%]

================= 119 passed, 2 skipped, 1 warning in 33.47s ==================
```

---

## 6. Artifact Immutability Verification

All 11 canonical Phase 1–4 artifacts were re-evaluated via SHA-256 against their established baselines:

| Artifact Path | Baseline SHA-256 Hash | Status |
| :--- | :--- | :---: |
| `data/raw/chicago_taxi_trips_2022-06.jsonl` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | **MATCH** |
| `docs/evidence/clean_run_summary.json` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | **MATCH** |
| `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | **MATCH** |
| `data/interim/excluded_trips_2022-06/excluded_trips.parquet` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | **MATCH** |
| `data/processed/zone_universe/zone_universe.parquet` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | **MATCH** |
| `data/processed/forecasts/forecasts.parquet` | `992A44F66F56F1E5579DDEFBE0EC445FF6D705D7E6B8F7EC9A50C1FF6180E7BD` | **MATCH** |
| `data/processed/forecasts/forecast_evaluation.parquet` | `F7629ACD43404EBE551C492DDE682CA348891D69AF77558E8012F6D925954ACB` | **MATCH** |
| `models/xgboost_demand_model.json` | `D80607A641E07968D51AF3EB0D85F38966C18381A86BC16AD3615C44EF39FA74` | **MATCH** |
| `data/processed/simulation/zone_pressure_status.parquet` | `7600A0CDB27C67B81BB2A6EF92B654F84535213AD02CDB4F2A9980B8295C9F9F` | **MATCH** |
| `data/processed/simulation/surge_alerts.parquet` | `E05844903DC5824E04FE64D376473FCC7308EC4FD5DEF84ABFE6066FF30E5082` | **MATCH** |
| `docs/evidence/phase4_supply_pressure_summary.json` | `BD5F7F41148B327E1B6D4C2BD2F70CF6A6A836C716E530A75AC4DA9C43ED7F2D` | **MATCH** |

**Invariance Result:** `ALL ARTIFACTS INVARIANT: True` (100% byte-for-byte fidelity).

---

## 7. Files Created & Modified

| File Path | Action | Description |
| :--- | :---: | :--- |
| `frontend/src/services/chicagoH3Zones.json` | **Created** | GeoJSON FeatureCollection of all 239 H3 Resolution 8 closed polygons. |
| `frontend/src/views/ChicagoMapView.jsx` | **Created** | Interactive Leaflet map, H3 choropleth heatmap, controls, legend, and zone inspector. |
| `frontend/test/mapGeoJSON.test.js` | **Created** | Unit tests for GeoJSON features, closed hex rings, coordinate bounds, and color tiers. |
| `frontend/package.json` | **Modified** | Added `leaflet` dependency (`^1.9.4`). |
| `frontend/src/index.css` | **Modified** | Imported `leaflet/dist/leaflet.css` and added dark theme container/popup overrides. |
| `frontend/src/components/Sidebar.jsx` | **Modified** | Added "Command Centre Map" navigation link. |
| `frontend/src/App.jsx` | **Modified** | Lazy loaded and routed `ChicagoMapView`. |
| `frontend/src/views/OverviewView.jsx` | **Modified** | Added deep link to Command Centre Map from shortage table. |
| `reports/phase1_fleet_map_report.md` | **Created** | This comprehensive Phase 1 verification report. |

---

## 8. Known Limitations & Phase 2 Boundary

1. **Phase 2 Scope Boundary (Strictly Preserved):**
   - No moving driver vehicles, animated taxi markers, customer trip lifecycles, or dispatch optimization were implemented. Those are reserved for Phase 2.
2. **Interactive Browser Automation:**
   - Headless browser drivers (Playwright / Puppeteer) are not installed on this host environment; visual verification was conducted via build compilation, node unit testing, and HTTP API validation.
3. **Kafka Live Streaming Infrastructure:**
   - 2 integration tests remain skipped due to the absence of a live Kafka broker on the host.

---

## 9. Final Verdict

**VERDICT: PASS WITH LIMITATIONS**

Phase 1 of the Fleet Simulation Command Centre is complete, fully tested, and ready for human review.

