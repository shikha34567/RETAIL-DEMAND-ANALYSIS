# RideIntel Phase 5B — Runtime Integration Audit & Implementation Report

**Date:** October 11, 2026  
**Project:** RideIntel — Chicago Ride Demand & Supply Intelligence System  
**Phase:** Phase 5B (React Frontend Runtime Integration & Optimization)  
**Overall Verdict:** **PASS WITH LIMITATIONS**  

---

## 1. Executive Summary

A comprehensive, evidence-based runtime audit of Phase 5B was conducted on the React single-page application (`frontend/`) and its integration with the FastAPI REST backend (`api/`).

### Status Breakdown:
- **BUILD VERIFIED:** Yes (`npm run build` completed in 1.44s; initial bundle reduced from 668.55 kB to 229.43 kB).
- **API VERIFIED:** Yes (All 6 documented `/api/v1` endpoints verified with HTTP 200 over live socket).
- **BROWSER VERIFIED:** HTTP Client Verified (Interactive browser automation tools like Playwright/Puppeteer are not configured in the host environment; all web routes, HTML payloads, JS/CSS assets, and API proxy routes verified over port 5173).
- **REGRESSION TESTS VERIFIED:** Yes (4 frontend unit tests passed; 118 Python backend tests passed, 2 integration tests skipped due to missing host Kafka brokers; 11 canonical Phase 1–4 artifacts verified 100% SHA-256 invariant).

---

## 2. Six Endpoints Live Runtime Verification

The FastAPI server running on `http://127.0.0.1:8000` was audited across all six endpoints:

| Endpoint | Backing Source | Status | Records Verified | Key Response Fields |
| :--- | :--- | :---: | :---: | :--- |
| `GET /api/v1/health` | Multi-artifact inspection | `200 OK` | 5 components | `status: HEALTHY`, all stores operational |
| `GET /api/v1/metadata` | `settings.yaml` + `zone_universe.parquet` | `200 OK` | N/A | `total_catalog_zones: 239`, `retrospective: 139`, `eligible: 135`, `active: 135` |
| `GET /api/v1/forecasts` | `forecasts.parquet` | `200 OK` | 116,505 | Default model `xgboost`, 30m horizon, UTC origins |
| `GET /api/v1/pressure` | `zone_pressure_status.parquet` | `200 OK` | 116,505 | $C = V \times 1.2$, null pressure index when $C=0$ |
| `GET /api/v1/surge-alerts` | `surge_alerts.parquet` | `200 OK` | 8 | Explicit `SIMULATED_ESTIMATE` disclaimer attached |
| `GET /api/v1/metrics` | `forecasting_evaluation_summary.json` | `200 OK` | 3 models | 116,505 identical test rows; XGBoost MAE 0.9310, RMSE 2.2366, WAPE 31.87% |

### Live Endpoint Query Output:
```text
=== /api/v1/health ===
Status: 200
Top keys: ['status', 'version', 'timestamp', 'components']

=== /api/v1/metadata ===
Status: 200
Top keys: ['dataset_period', 'split_boundary_utc', 'storage_timezone', 'display_timezone', 'forecast_eligible_zones', 'operational_zone_count', 'retrospective_operational_zones', 'total_catalog_zones', 'h3_resolution', 'window_minutes', 'forecast_horizon_minutes', 'available_models', 'default_model', 'source_labels', 'streaming_status', 'supply_data_status', 'disclaimer']
Catalog: 239 Retro: 139 Eligible: 135 Active: 135

=== /api/v1/forecasts?limit=5 ===
Status: 200
Total records: 116505 Returned: 5

=== /api/v1/pressure?limit=5 ===
Status: 200
Total records: 116505 Returned: 5

=== /api/v1/surge-alerts?limit=5 ===
Status: 200
Total records: 8 Returned: 5

=== /api/v1/metrics ===
Status: 200
Models in metrics: ['xgboost', 'baseline_rolling_avg', 'baseline_same_time_last_week']
```

---

## 3. Vite Proxy and Route Verification

Vite dev server running on port 5173 proxies `/api/*` requests to `http://127.0.0.1:8000`. Direct HTTP audit through `http://localhost:5173` yielded:

```text
http://localhost:5173/ -> 200 text/html (631 bytes)
http://localhost:5173/api/v1/health -> 200 application/json (853 bytes)
http://localhost:5173/api/v1/metadata -> 200 application/json (1072 bytes)
http://localhost:5173/api/v1/forecasts?limit=10 -> 200 application/json (3245 bytes)
http://localhost:5173/api/v1/pressure?limit=10 -> 200 application/json (7205 bytes)
http://localhost:5173/api/v1/surge-alerts -> 200 application/json (2704 bytes)
http://localhost:5173/api/v1/metrics -> 200 application/json (16295 bytes)
```

---

## 4. Confirmed Defects and Applied Fixes

During the runtime integration audit, three concrete defects were discovered and resolved:

1. **Overview Chart Time Label Defect:**
   - *Problem:* In `OverviewView.jsx`, constructing the X-axis time label with `formatChicagoTime(timeKey).split(',')[1]?.trim()` yielded the year `"2022"` instead of the time (because `formatChicagoTime` outputs `"Jun 22, 2022, 12:00 AM CDT"`, where index 1 is `" 2022"`).
   - *Fix:* Added and exported a dedicated `formatChicagoTimeOnly(utcString)` helper in `frontend/src/services/api.js` that directly formats the time portion in `America/Chicago` (e.g. `12:00 AM CDT`). Updated `OverviewView.jsx` to use it.
   - *Test:* Added unit test verifying `formatChicagoTimeOnly` outputs the correct CDT time.

2. **Null Pressure Ratio Safe Type Checking:**
   - *Problem:* Checking `pressure_index !== null` in tables did not safeguard against `undefined` or zero-value conversions.
   - *Fix:* Standardized to `typeof r.pressure_index === 'number' ? r.pressure_index.toFixed(2) : 'null (C=0)'` across `ZoneIntelligenceView.jsx` and `OverviewView.jsx`.

3. **System Status Model Card Static Metrics:**
   - *Problem:* `SystemStatusView.jsx` previously had static fallback text for WAPE and MAE rather than reading the live evaluation summary from the backend.
   - *Fix:* Integrated `fetchMetrics()` into `SystemStatusView.jsx` so the Model Champion card dynamically displays actual API metrics from `forecasting_evaluation_summary.json` (WAPE: 31.87% | MAE: 0.9310).

4. **Vite 8 / Rolldown Bundle Optimization:**
   - *Problem:* The monolithic build bundle was 668.55 kB, triggering Vite warnings about chunks > 500 kB.
   - *Fix:* Implemented route-level lazy loading (`React.lazy` and `Suspense`) in `App.jsx` for the four secondary views, and configured Rolldown `manualChunks` in `vite.config.js` to isolate `vendor-charts` and `vendor-icons`.
   - *Result:* Reduced initial bundle size from **668.55 kB** down to **229.43 kB** (gzip: **71.26 kB**). All chunks are now under 400 kB with zero Vite chunk-size warnings.

---

## 5. Test Suite and Build Execution Results

### 5.1 Frontend Unit Tests (`npm test`)
Command: `npm test` inside `frontend/`
```text
> frontend@0.0.0 test
> node --test test/*.test.js

✔ formatChicagoTime converts UTC to Chicago Daylight Time (CDT) (23.9817ms)
✔ formatChicagoTimeOnly formats time portion in America/Chicago (0.8638ms)
✔ formatChicagoTime handles empty, null and invalid inputs gracefully (0.2525ms)
✔ ApiError preserves HTTP status and payload detail (1.3184ms)
ℹ tests 4
ℹ suites 0
ℹ pass 4
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 148.2967
```

### 5.2 Frontend Production Build (`npm run build`)
Command: `npm run build` inside `frontend/`
```text
> frontend@0.0.0 build
> vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 2492 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                 0.78 kB │ gzip:   0.38 kB
dist/assets/index-6a-ln0fp.css                 41.71 kB │ gzip:   7.54 kB
dist/assets/rolldown-runtime-hePW80VL.js        0.71 kB │ gzip:   0.42 kB
dist/assets/api-BbzzZZ5E.js                     4.73 kB │ gzip:   1.99 kB
dist/assets/SurgeAlertsView-CpeC8pX1.js         6.37 kB │ gzip:   2.09 kB
dist/assets/ZoneIntelligenceView-kVB5esb6.js    7.39 kB │ gzip:   2.29 kB
dist/assets/vendor-icons-oazISHLN.js            8.87 kB │ gzip:   3.51 kB
dist/assets/ModelPerformanceView-_QKsQMoZ.js    9.75 kB │ gzip:   2.47 kB
dist/assets/SystemStatusView-CYnm7Mi3.js       12.45 kB │ gzip:   3.10 kB
dist/assets/index-CfpPp3YG.js                 229.43 kB │ gzip:  71.26 kB
dist/assets/vendor-charts-BXQSVD6x.js         393.19 kB │ gzip: 112.49 kB

✓ built in 1.44s
```

### 5.3 Backend Pytest Suite (`python -m pytest`)
Command: `python -m pytest` from repository root
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2
collected 120 items

tests\integration\test_streaming_pipeline.py ss                          [  1%]
tests\unit\test_api_forecasts.py .........                               [  9%]
tests\unit\test_api_health.py ....                                       [ 12%]
tests\unit\test_api_immutability.py .                                    [ 13%]
tests\unit\test_api_metrics.py ....                                      [ 16%]
tests\unit\test_api_pressure.py .........                                [ 24%]
tests\unit\test_api_surge.py ......                                      [ 29%]
tests\unit\test_clean_pipeline.py ......                                 [ 34%]
tests\unit\test_cleaning_policy.py ........                              [ 40%]
tests\unit\test_forecasting_aggregation.py ......                        [ 45%]
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

============================== warnings summary ===============================
..\..\..\AppData\Local\Programs\Python\Python313\Lib\site-packages\fastapi\testclient.py:1
  StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.

================= 118 passed, 2 skipped, 1 warning in 41.70s ==================
```

---

## 6. Artifact Hash Invariance Audit

All 11 canonical Phase 1–4 artifacts were audited via SHA-256 against their established baseline manifests:

| Canonical Artifact Path | Established Baseline SHA-256 | Current Computed SHA-256 | Status |
| :--- | :--- | :--- | :---: |
| `data/raw/chicago_taxi_trips_2022-06.jsonl` | `C87B096AD1D24392...` | `C87B096AD1D24392...` | **MATCH** |
| `docs/evidence/clean_run_summary.json` | `66C866BA44F94939...` | `66C866BA44F94939...` | **MATCH** |
| `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet` | `8472B1957464B5B7...` | `8472B1957464B5B7...` | **MATCH** |
| `data/interim/excluded_trips_2022-06/excluded_trips.parquet` | `E13E16642ECF0CC1...` | `E13E16642ECF0CC1...` | **MATCH** |
| `data/processed/zone_universe/zone_universe.parquet` | `5FB738D3E99A4DB0...` | `5FB738D3E99A4DB0...` | **MATCH** |
| `data/processed/forecasts/forecasts.parquet` | `992A44F66F56F1E5...` | `992A44F66F56F1E5...` | **MATCH** |
| `data/processed/forecasts/forecast_evaluation.parquet` | `F7629ACD43404EBE...` | `F7629ACD43404EBE...` | **MATCH** |
| `models/xgboost_demand_model.json` | `D80607A641E07968...` | `D80607A641E07968...` | **MATCH** |
| `data/processed/simulation/zone_pressure_status.parquet` | `7600A0CDB27C67B8...` | `7600A0CDB27C67B8...` | **MATCH** |
| `data/processed/simulation/surge_alerts.parquet` | `E05844903DC5824E...` | `E05844903DC5824E...` | **MATCH** |
| `docs/evidence/phase4_supply_pressure_summary.json` | `BD5F7F41148B327E...` | `BD5F7F41148B327E...` | **MATCH** |

**Verification Result:** `ALL ARTIFACTS INVARIANT: True`

---

## 7. Known Limitations & Blockers

1. **Kafka Integration Tests Skipped (Known Infrastructure Limitation):**
   - 2 integration tests (`tests/integration/test_streaming_pipeline.py`) remain skipped because real Kafka broker infrastructure (Docker daemon / WSL2) is unavailable on this host environment. The PySpark structured streaming core remains verified under pure-JVM simulation tests.
2. **Interactive Browser Automation Tooling:**
   - Headless browser drivers (Puppeteer/Playwright) are not installed in this environment; visual verification relies on HTTP client asset inspection and standard browser testing via localhost.

---

## 8. Final Verdict

**VERDICT: PASS WITH LIMITATIONS**

The React frontend and FastAPI integration meet all runtime, contract, performance, and immutability standards. Zero regressions were introduced.
