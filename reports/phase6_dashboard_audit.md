# RideIntel Phase 6 — Analytics Dashboard Audit and Fixes Report

**Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand & Supply Intelligence System  
**Phase:** Phase 6 (Analytics Dashboard Audit, Overview Graph Overhaul, Canonical H3 Labels, NO_CAPACITY Investigation)  
**Author:** Lead Full-Stack & ML Systems Engineer (Antigravity)  
**Status:** Complete  
**Final Verdict:** **PASS WITH LIMITATIONS** (All offline frontend and backend test suites passing; 11 canonical Phase 1–4 artifacts strictly invariant; live Kafka broker and interactive browser automation drivers unavailable on host)

---

## Executive Summary

Phase 6 performed a rigorous, evidence-based audit and targeted enhancement of the RideIntel analytics dashboards. It successfully resolved the root cause of the non-functioning Overview area chart, introduced an invariant canonical friendly labeling taxonomy (`Zone Z-001` through `Zone Z-239`) across Chicago's H3 Resolution 8 spatial cells, conducted an exhaustive mathematical audit of the 33.63% `NO_CAPACITY` records, and integrated clear contextual callouts into the user interface without altering API contracts or mutating historical/simulated data artifacts.

All 11 canonical Phase 1–4 artifacts retain 100% byte-for-byte SHA-256 hash invariance. The backend test suite passes with **118 passed, 2 skipped** (Kafka integration tests safely skipped), and the frontend test suite passes with **8 passed, 0 failed**.

---

## 1. Root Cause Analysis: Overview Dashboard Graph Failure

### 1.1 The Failure Mode
Prior to Phase 6, the Overview page featured an area chart titled *"Predicted Demand vs Estimated Capacity"*. In production, this chart rendered as either a flat, empty line or an uninformative single-point representation.

### 1.2 Quantitative Root Cause
A thorough code trace of `frontend/src/views/OverviewView.jsx` revealed the structural flaw:
1. **Unbounded Time Horizon with Arbitrary Pagination Limit:** The component called the API endpoint with `fetchPressure({ limit: 100 })`.
2. **Zone Density per Origin:** In the RideIntel processing pipeline, every 15-minute prediction origin $T$ evaluates exactly $N = 135$ operational forecast zones.
3. **Truncated Spatial Sampling:** Fetching only 100 records resulted in returning only 100 out of 135 zones for the single earliest chronological origin in the dataset (`2022-06-22 05:00:00Z`).
4. **Single-Bucket Collapse:** When the chart logic grouped records by `prediction_origin` to display a time series, the entire array collapsed into a **single time bucket** with incomplete spatial aggregation (100 zones instead of 135). A time-series chart cannot render a meaningful curve or trend across a single timestamp.
5. **Loss of Geographic Granularity:** Attempting to plot a city-wide aggregate demand line against capacity concealed critical localized imbalances: shortages in dense downtown zones were mathematically canceled out by surplus capacity in outlying residential zones.

---

## 2. Overview Dashboard Redesign & Actionable Intelligence

### 2.1 Design Objectives
Rather than displaying a misleading temporal aggregation of an incomplete zone sample, the Overview dashboard was overhauled to answer the core operational question:
> **"Will predicted ride demand exceed estimated capacity, and where is a shortage expected?"**

### 2.2 Implemented Improvements
1. **Origin Snapshot Selector:** Users can select representative temporal snapshots across the test horizon (e.g., *Jun 22, 12:00 AM CDT*, *Jun 22, 08:00 AM CDT Peak*, *Jun 22, 05:00 PM CDT Peak*, *Jun 24 Night Weekend*, *Jun 30 Midday*).
2. **Complete Spatial Snapshot Query:** For each selected origin, the frontend queries all 135 operational zones (`limit: 150`), guaranteeing 100% spatial coverage without arbitrary truncation.
3. **Direct Demand vs. Capacity Grouped Bar Chart:** 
   - Compares Predicted Demand $D$ vs. Estimated Capacity $C$ in identical, compatible units (**rides per 30 minutes**).
   - Displays the Top 12 zones sorted by user-selectable criteria:
     - **Largest Shortage ($D - C$):** Immediately highlights vulnerable shortage zones.
     - **Highest Demand ($D$):** Identifies major activity centers.
     - **Highest Capacity ($C$):** Shows fleet concentration.
4. **Ranked Top Shortage Zones Table:**
   - Explicitly displays friendly zone labels (`Zone Z-XXX`), raw H3 hex IDs, predicted demand, simulated capacity, and expected unserved rides ($\max(0, D - C)$).
   - Badges pressure levels (`CRITICAL`, `HIGH`, `MODERATE`, `LOW`, `NO_CAPACITY`).
5. **Snapshot Pressure Distribution Breakdown:**
   - Visual distribution bar and summary stats showing the exact breakdown across the 135 zones (counts and percentages of Low, Moderate, High, Critical, and No Capacity).
6. **Transparent NO_CAPACITY Callout:**
   - Explains directly to the user why certain peripheral zones have $C = 0$ due to multinomial fleet sampling of micro-demand.

---

## 3. Canonical H3 Geographic Zone Label System

### 3.1 Principles and Governance
In strict adherence to project rules:
- No artificial neighborhood or community area names were invented or guessed.
- The raw Resolution 8 H3 hexadecimal strings remain the primary technical keys.
- Friendly labels provide human readability, sorting stability, and deterministic cross-dashboard consistency.

### 3.2 Canonical Implementation
1. **Catalog Generation (`frontend/src/services/zoneCatalog.json`):**
   - Extracted all 239 Resolution 8 cells from the immutable `zone_universe.parquet`.
   - Sorted cells deterministically in ascending alphanumeric order.
   - Assigned zero-padded canonical labels from `Zone Z-001` through `Zone Z-239`.
   - Derived exact geographic centroids (`latitude`, `longitude`) for each cell using `h3.cell_to_latlng` at Resolution 8.
2. **Label Helper Service (`frontend/src/services/zoneLabels.js`):**
   - `getZoneLabel(h3Index)`: Returns canonical label (e.g., `Zone Z-042`) or fallback `Zone <prefix>`.
   - `getZoneDetails(h3Index)`: Returns object with `label`, `h3_index`, `lat`, `lng`, and `resolution: 8`.
   - `getAllZoneLabels()`: Returns all 239 sorted catalog entries.
3. **Cross-Dashboard Integration:**
   - **Overview:** Top shortage table and chart tooltips display `Zone Z-XXX`.
   - **Zone Intelligence:** Filter dropdown lists `Zone Z-XXX — 882664c1...`; table displays friendly labels prominently with quick-copy for raw hex IDs.
   - **Surge Alerts:** Alert cards display `Zone Z-XXX` above raw H3 hex strings.
   - **System Status:** Excluded/quarantined retrospective cells display friendly labels alongside hex IDs.

---

## 4. Deep-Dive Audit of `NO_CAPACITY` Status ($C=0$, 33.63%)

### 4.1 Artifact Statistics
An exhaustive analysis of all 116,505 rows in `data/processed/simulation/zone_pressure_status.parquet` was conducted:

| Metric | Measured Value |
| :--- | :--- |
| Total Zone-Window Records | 116,505 |
| `NO_CAPACITY` Records | **39,183 (33.63%)** |
| `LOW` Pressure Records | 48,011 (41.21%) |
| `MODERATE` Pressure Records | 25,626 (22.00%) |
| `HIGH` Pressure Records | 3,115 (2.67%) |
| `CRITICAL` Pressure Records | 570 (0.49%) |
| Numeric Pressure Index for $C=0$ | `null` (100% compliant with schema contract) |
| Infinity Serialized | **0 (Zero)** |

### 4.2 Mathematical Root Cause
1. **Vehicle Allocation Priors:** In Phase 4, the synthetic fleet size $V_{total}(T) \in [1000, 2125]$ vehicles is distributed across 135 operational zones using a multinomial distribution $\text{Multinomial}(V_{total}, \mathbf{p})$, where $\mathbf{p}$ is proportional to historical training demand volume.
2. **Micro-Demand in Peripheral Cells:** Outlying zones have historical trip fractions under $0.01\%$. In any given 15-minute draw, the integer count of available vehicles allocated to these peripheral zones is frequently **$V_z = 0$**.
3. **Zero Effective Capacity:** Since effective capacity is $C_z = V_z \times r_z$ (where $r_z \approx 1.25$ rides/vehicle), $V_z = 0 \implies C_z = 0$.
4. **Non-Zero XGBoost Predictions:** The XGBoost model predicts fractional positive demand in these zones (e.g., $D_z = 0.08$ rides/30m).
5. **Distribution of Demand when $C = 0$:**
   - Mean predicted demand: **0.1524 rides / 30m**
   - Median predicted demand: **0.0900 rides / 30m**
   - Demand $< 1.0$ ride: **38,711 of 39,183 (98.80%)**
   - Demand $< 0.5$ ride: **36,926 of 39,183 (94.24%)**
   - Max demand observed: **18.78 rides / 30m**

### 4.3 Governance & Integrity Conclusions
- `NO_CAPACITY` is **not a pipeline defect, missing telemetry, or data corruption**. It accurately reflects the simulated supply model where a finite taxi fleet does not station vehicles in low-demand peripheral zones during off-peak hours.
- Arbitrarily inflating fleet sizes or deleting $C = 0$ records would violate scientific integrity and fabricate supply where none existed in the simulation.
- **Contract Conformance:** In accordance with `contracts/parquet_schemas.md`, when $C = 0$ and $D > 0$, `pressure_ratio` and `pressure_index` MUST be `null`, while `pressure_level` is categorized as `NO_CAPACITY`. No division-by-zero or `Infinity` values exist.

---

## 5. Preservation of Existing Dashboards & Contract Conformance

- **API Contracts Preserved:** All endpoints in `api/` (`/api/v1/health`, `/api/v1/metadata`, `/api/v1/forecasts`, `/api/v1/pressure`, `/api/v1/surge-alerts`, `/api/v1/metrics`) retain exact schemas and behavioral contracts.
- **Model Performance View:** Unchanged; displays held-out test evaluation metrics (WAPE, MAE, RMSE) for XGBoost, Rolling Average, and Same Time Last Week baselines.
- **System Governance / Status View:** Preserved; displays pipeline lineage, data split boundaries, H3 resolution trade-offs, and quarantined cells.
- **Surge Alerts View:** Preserved; shows real-time alert cards, surge multipliers, and persistent alert thresholds.
- **Design System:** Consistent Tailwind CSS dark theme (`#0F172A`, `#1E293B`, `#334155`), accessible typography, and Lucide icons.

---

## 6. Test Suite Execution & Output

### 6.1 Frontend Test Suite (`node --test test/*.test.js`)
```text
> frontend@0.0.0 test
> node --test test/*.test.js

✔ formatChicagoTime converts UTC to Chicago Daylight Time (CDT) (58.1042ms)
✔ formatChicagoTimeOnly formats time portion in America/Chicago (0.4911ms)
✔ formatChicagoTime handles empty, null and invalid inputs gracefully (0.1987ms)
✔ ApiError preserves HTTP status and payload detail (1.0808ms)
✔ getZoneLabel returns deterministic friendly label for known cell (1.186ms)
✔ getZoneLabel handles null, undefined and unknown gracefully (0.1651ms)
✔ getZoneDetails returns valid coordinates and resolution (0.4935ms)
✔ getAllZoneLabels returns all 239 catalog entries sorted (0.2057ms)
ℹ tests 8
ℹ suites 0
ℹ pass 8
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 191.0437
```

### 6.2 Frontend Lint (`npm run lint`)
```text
> frontend@0.0.0 lint
> oxlint

Found 3 warnings (effect hook optimization notices) and 0 errors.
Finished in 88ms on 17 files with 104 rules using 8 threads.
```

### 6.3 Frontend Production Build (`npm run build`)
```text
> frontend@0.0.0 build
> vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 2494 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                 0.78 kB │ gzip:   0.37 kB
dist/assets/index-BbK0rkD5.css                 43.42 kB │ gzip:   7.81 kB
dist/assets/rolldown-runtime-hePW80VL.js        0.71 kB │ gzip:   0.42 kB
dist/assets/api-c7chiWEW.js                     4.49 kB │ gzip:   1.96 kB
dist/assets/SurgeAlertsView-DwMeg6j4.js         6.52 kB │ gzip:   2.11 kB
dist/assets/ZoneIntelligenceView-2KQy4Hrz.js    8.52 kB │ gzip:   2.62 kB
dist/assets/vendor-icons-tinjcOwx.js            9.12 kB │ gzip:   3.59 kB
dist/assets/ModelPerformanceView-B8RIHPPf.js    9.75 kB │ gzip:   2.47 kB
dist/assets/SystemStatusView-D6a3JJNt.js       12.62 kB │ gzip:   3.14 kB
dist/assets/index-BoJOsRQn.js                 264.88 kB │ gzip:  79.18 kB
dist/assets/vendor-charts-DdmkzTbP.js         382.05 kB │ gzip: 110.15 kB

✓ built in 3.29s
```

### 6.4 Backend Pytest Suite (`python -m pytest`)
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
  C:\Users\91984\AppData\Local\Programs\Python\Python313\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 118 passed, 2 skipped, 1 warning in 43.39s ==================
```

---

## 7. Canonical Phase 1–4 Artifact Hash Invariance Audit

All 11 canonical Phase 1–4 data and model artifacts were evaluated via SHA-256 against their established baselines:

| Canonical Artifact Path | Baseline SHA-256 Hash | Audited SHA-256 Hash | Status |
| :--- | :--- | :--- | :---: |
| `data/raw/chicago_taxi_trips_2022-06.jsonl` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | **MATCH** |
| `docs/evidence/clean_run_summary.json` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | **MATCH** |
| `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | **MATCH** |
| `data/interim/excluded_trips_2022-06/excluded_trips.parquet` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | **MATCH** |
| `data/processed/zone_universe/zone_universe.parquet` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | **MATCH** |
| `data/processed/forecasts/forecasts.parquet` | `992A44F66F56F1E5579DDEFBE0EC445FF6D705D7E6B8F7EC9A50C1FF6180E7BD` | `992A44F66F56F1E5579DDEFBE0EC445FF6D705D7E6B8F7EC9A50C1FF6180E7BD` | **MATCH** |
| `data/processed/forecasts/forecast_evaluation.parquet` | `F7629ACD43404EBE551C492DDE682CA348891D69AF77558E8012F6D925954ACB` | `F7629ACD43404EBE551C492DDE682CA348891D69AF77558E8012F6D925954ACB` | **MATCH** |
| `models/xgboost_demand_model.json` | `D80607A641E07968D51AF3EB0D85F38966C18381A86BC16AD3615C44EF39FA74` | `D80607A641E07968D51AF3EB0D85F38966C18381A86BC16AD3615C44EF39FA74` | **MATCH** |
| `data/processed/simulation/zone_pressure_status.parquet` | `7600A0CDB27C67B81BB2A6EF92B654F84535213AD02CDB4F2A9980B8295C9F9F` | `7600A0CDB27C67B81BB2A6EF92B654F84535213AD02CDB4F2A9980B8295C9F9F` | **MATCH** |
| `data/processed/simulation/surge_alerts.parquet` | `E05844903DC5824E04FE64D376473FCC7308EC4FD5DEF84ABFE6066FF30E5082` | `E05844903DC5824E04FE64D376473FCC7308EC4FD5DEF84ABFE6066FF30E5082` | **MATCH** |
| `docs/evidence/phase4_supply_pressure_summary.json` | `BD5F7F41148B327E1B6D4C2BD2F70CF6A6A836C716E530A75AC4DA9C43ED7F2D` | `BD5F7F41148B327E1B6D4C2BD2F70CF6A6A836C716E530A75AC4DA9C43ED7F2D` | **MATCH** |

**Verification Outcome:** `ALL ARTIFACTS INVARIANT: True` (100% byte-for-byte fidelity).

---

## 8. Real Runtime Status & Known Infrastructure Boundaries

1. **Interactive Browser Automation:**
   - Interactive browser automation drivers (such as Playwright, Puppeteer, or Selenium) are not installed in this execution environment. Verification of the UI components was conducted via node unit tests, production build compilation, HTTP asset inspection, and component static analysis.
2. **Kafka Live Streaming Tests:**
   - 2 integration tests (`tests/integration/test_streaming_pipeline.py`) remain skipped because live Kafka brokers (Docker / WSL2) are not available on this host. PySpark streaming logic remains validated via unit simulation.
3. **Backend API Live Status:**
   - FastAPI server verified responsive on `http://127.0.0.1:8000/api/v1/health` with HTTP status 200.

---

## 9. Summary of Modified & Added Files

| File Path | Action | Description |
| :--- | :---: | :--- |
| `frontend/src/services/zoneCatalog.json` | **Created** | Canonical catalog mapping all 239 Resolution 8 cells to `Zone Z-001` .. `Zone Z-239` with centroids. |
| `frontend/src/services/zoneLabels.js` | **Created** | Lookup utilities for zone labels, coordinates, and full catalog retrieval. |
| `frontend/test/zoneLabels.test.js` | **Created** | Node test suite covering deterministic label lookup, coordinates, and graceful fallback. |
| `frontend/src/views/OverviewView.jsx` | **Modified** | Replaced broken aggregate area chart with complete-snapshot Demand vs Capacity grouped bar chart, shortage table, distribution bar, and NO_CAPACITY notice. |
| `frontend/src/views/ZoneIntelligenceView.jsx` | **Modified** | Added friendly zone labels to dropdown selector, table rows, and added NO_CAPACITY explanation callout. |
| `frontend/src/views/SurgeAlertsView.jsx` | **Modified** | Integrated canonical zone labels on surge alert cards. |
| `frontend/src/views/SystemStatusView.jsx` | **Modified** | Integrated canonical zone labels for quarantined retrospective zones. |
| `reports/phase6_dashboard_audit.md` | **Created** | This comprehensive audit and verification report. |

---

## 10. Final Verdict

**VERDICT: PASS WITH LIMITATIONS**

The Phase 6 objectives are fully achieved. The Overview visualization has been restored with honest, actionable demand-capacity intelligence; the H3 spatial catalog provides unambiguous canonical zone labels across all views; the 33.63% NO_CAPACITY status is mathematically explained and transparently presented; and all underlying Phase 1–4 models, data, and contracts remain strictly immutable.

