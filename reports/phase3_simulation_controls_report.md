# RideIntel Fleet Simulation Command Centre — Phase 3 Report
## Simulation Controls, Live KPIs & Integrated Command Centre

**Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand & Supply Intelligence System  
**Phase:** Fleet Simulation Command Centre — Phase 3 (Simulation Controls, Live KPI Bar, Interactive Trip Telemetry & Command Centre Integration)  
**Author:** Lead Full-Stack & ML Systems Engineer (Antigravity)  
**Status:** Complete  
**Final Verdict:** **PASS WITH LIMITATIONS** (All offline frontend and backend unit tests passing; Vite production build passing; 11 canonical Phase 1–4 artifacts strictly invariant; live Kafka broker and interactive browser drivers unavailable on host)

---

## Executive Summary

Phase 3 unifies the spatial visualization, simulation engine, and demand forecasting of RideIntel into a high-performance, map-first **Fleet Simulation Command Centre**. The implementation achieves:

1. **Complete Simulation Controls:** Start (Play), Pause, Resume, and deterministic Reset controls; variable simulation speed multipliers (`0.5x`, `1x`, `2x`, `4x`); manual single-step advancement (+15s sim time); and safe in-flight request locking (`isSteppingRef`) preventing clock jitter or overlapping server calls.
2. **Live Operations KPI Bar:** A top-level operational telemetry bar deriving metrics strictly from authoritative backend simulation state ($N = 60$ total fleet, idle drivers, repositioning fleet, passenger trips, unserved/active customer requests, fulfilled demand, clock tick, and step rate). Enforces explicit fleet conservation reconciliation ($60 = V_{idle} + V_{repo} + V_{pickup} + V_{pax} + V_{off}$).
3. **Integrated XGBoost Demand & Dynamic Zone Pressure:** Retains the Resolution 8 forecast heatmap. On zone inspection, dynamically derives live capacity ($C = V_{idle} \times 2.0$), expected shortage ($\max(0, D - C)$), incoming repositioning vehicles, and contract-compliant pressure levels (including `NO_CAPACITY` with null numeric index when $C = 0, D > 0$).
4. **Interactive Customer Trip Lifecycle & Map Markers:** Distinct pickup (`[P]`, Emerald) and dropoff (`[D]`, Rose) Leaflet map markers for all active customer trips with interactive tooltips and toggle controls (`showCustomerMarkers`). Dedicated Customer Trip Telemetry inspection card with cross-navigation to assigned drivers.
5. **Bidirectional Driver & Trip Linking:** Clicking a driver in `TO_PICKUP` or `WITH_PASSENGER` displays the assigned customer trip with a one-click inspection shortcut. Clicking a customer trip links directly to the assigned driver's kinematics and live coordinates.
6. **Artifact Invariance:** All 11 canonical Phase 1–4 historical data, model, and evidence artifacts remain 100% byte-for-byte SHA-256 invariant.

---

## 1. Simulation Controls & Clock Architecture

### 1.1 Variable Speed & Stepping Intervals
The simulation clock advances in discrete increments of $\Delta t = 15$ seconds (`POST /api/v1/simulation/step {"seconds": 15}`). The speed multiplier governs the real-time polling interval, ensuring physical vehicle speed ($32.0\text{ km/h}$) and trip distances are strictly preserved across all speeds:

$$\text{intervalMs} = \text{round}\left(\frac{1000}{\text{simSpeed}}\right)$$

| Speed Multiplier | Interval (ms) | Simulation Advance Rate | Purpose |
| :---: | :---: | :---: | :--- |
| `0.5x` | 2000 ms | 15s sim time / 2.0s real time | Detailed kinematic inspection of vehicle trajectories |
| `1.0x` | 1000 ms | 15s sim time / 1.0s real time | Standard operational playback |
| `2.0x` | 500 ms | 15s sim time / 0.5s real time | Accelerated fleet repositioning observation |
| `4.0x` | 250 ms | 15s sim time / 0.25s real time | Fast-forward multi-trip lifecycle evaluation |

### 1.2 In-Flight Stepping Guard (`isSteppingRef`)
To prevent concurrent asynchronous step requests from overlapping (especially under high-frequency `4x` stepping or temporary network latency), a strict in-flight reference guard is enforced:
```javascript
const isSteppingRef = useRef(false);

// Auto-stepping loop
if (isSteppingRef.current) return;
isSteppingRef.current = true;
try {
  const updatedState = await stepSimulation(15);
  setSimState(updatedState);
} catch {
  setIsPlaying(false);
} finally {
  isSteppingRef.current = false;
}
```
If an HTTP request takes longer than the interval duration, the next tick is safely skipped rather than queueing concurrent requests, eliminating clock drift and race conditions.

### 1.3 Deterministic Reset
Clicking **Reset Simulation** (`RotateCcw`):
1. Immediately cancels active auto-stepping timers (`clearInterval`) and resets `isPlaying` to `false`.
2. Resets in-flight locks (`isSteppingRef.current = false`).
3. Calls `POST /api/v1/simulation/reset` to restore the backend engine to tick 0, clears all customer trips, and repositions all 60 drivers to their seeded initial zones.
4. Clears active selection states (`selectedDriver = null`, `selectedZone = null`, `selectedTrip = null`, `dispatchResult = null`).

---

## 2. Live Operations KPI Bar & Fleet Conservation

The Command Centre features a persistent 6-card **Live Operations KPI Bar** displayed above the map view:

```text
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│  Clock & Rate   │Fleet Conserved  │Available Idle(V)│ Repositioning   │ Customer Trips  │ Completed Rides │
│  Tick #14 (2x)  │ 60/60 Conserved │     48 veh      │      8 veh      │    4 active     │     6 rides     │
│ [Play] [Step]   │ 100% Conserved  │ Cap C=96.0 r/30m│ En Route Deficit│ 2 req • 2 serv  │ Cumulative Done │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

### 2.1 Fleet Conservation Reconciliation Invariant
The total fleet size ($N = 60$) is strictly conserved at all times:
$$\sum (\text{IDLE} + \text{REPOSITIONING} + \text{TO\_PICKUP} + \text{WITH\_PASSENGER} + \text{OFF\_DUTY}) \equiv 60$$

- **In-Transit Supply Isolation:** In-transit vehicles (`REPOSITIONING`, `TO_PICKUP`, `WITH_PASSENGER`) are strictly excluded from available zone supply ($V_z$) at both departure and destination zones.
- **Arrival Crediting:** Only upon reaching destination (`route_progress == 1.0`) is a vehicle added to destination supply ($V_{dest}$) and marked `IDLE`.
- **Conservation Indicator:** If the sum of all states equals 60, the KPI card renders a green `ShieldCheck` badge (`60 / 60 Conserved`); otherwise, it flags an alert.

---

## 3. XGBoost Forecast Demand & Dynamic Zone Pressure

### 3.1 Map Heatmap Preservation
The H3 Resolution 8 demand forecast heatmap is maintained from Phase 1 and 2, color-coding cells by XGBoost predicted demand ($D_z$) across 6 threshold tiers:
- `< 0.1` (Trace): Slate (`#334155`)
- `0.1 – 1.0` (Low): Sky Blue (`#0284c7`)
- `1.0 – 5.0` (Moderate): Cyan (`#06b6d4`)
- `5.0 – 15.0` (Elevated): Emerald (`#10b981`)
- `15.0 – 35.0` (High): Amber (`#f59e0b`)
- `> 35.0` (Surge Core): Rose (`#f43f5e`)

### 3.2 Dynamic Zone Inspection Telemetry
Clicking an H3 hexagon displays live simulation-derived supply alongside historical model predictions:
- **Predicted Demand ($D$):** XGBoost predicted rides / 30 min for the selected snapshot origin.
- **Live Fleet Capacity ($C$):** $C = V_{idle} \times 2.0$ rides / 30 min ($r = 2.0$ rides/veh/30m).
- **Unserved Shortage:** $\max(0, D - C)$ rides.
- **Incoming Repositioning:** Number of vehicles dispatched and en route to the zone.
- **Occupied Vehicles:** Vehicles currently picking up or carrying passengers within the zone.
- **Pressure Level & Status Contract:**
  - If $C = 0$ and $D > 0$: `NO_CAPACITY` / `NO_ESTIMATED_CAPACITY` (numeric index is `null` by contract; never serialized as infinity).
  - If $C = 0$ and $D = 0$: `LOW` / `NORMAL`.
  - If $D / C < 0.5$: `LOW` / `NORMAL`.
  - If $0.5 \le D/C < 0.9$: `MODERATE` / `BALANCED`.
  - If $0.9 \le D/C < 1.2$: `HIGH` / `HIGH_PRESSURE`.
  - If $D/C \ge 1.2$: `CRITICAL` / `CRITICAL_DEFICIT`.

---

## 4. Customer Trip Markers & Interactive Drawer Integration

### 4.1 Leaflet Map Trip Markers
Active customer trips are plotted directly on the map in a dedicated layer (`customerMarkersLayerRef`):
- **Pickup Marker `[P]`:** Emerald circle marker (`#10b981`) at `[trip.pickup_lat, trip.pickup_lng]`.
- **Dropoff Marker `[D]`:** Rose circle marker (`#f43f5e`) at `[trip.dropoff_lat, trip.dropoff_lng]`.
- **Toggle Control:** `Pickups/Dropoffs` button in the map toolbar toggles visibility without affecting driver or heatmap layers.
- **Click Behavior:** Clicking either `[P]` or `[D]` opens the **Customer Trip Telemetry** card.

### 4.2 Interactive Active Customer Trips Drawer
Located in the right inspection column below the primary card:
- Displays all currently active trips (`REQUESTED`, `ASSIGNED`, `ON_TRIP`).
- Clickable trip items with active border highlight (`border-cyan-500`).
- Color-coded status badges: `REQUESTED` (Amber), `ASSIGNED` (Cyan), `ON_TRIP` (Purple).
- Inline **Cancel** button (enabled for `REQUESTED` and `ASSIGNED` states; disabled once passenger is on board).

### 4.3 Customer Trip Inspection Card
When a trip is selected:
- **Request ID:** e.g., `REQ-0004-001`.
- **Status & Source:** Status badge with `SIMULATED` source-type tag.
- **Pickup Telemetry:** Friendly zone label, H3 Resolution 8 index, and exact latitude/longitude coordinates.
- **Dropoff Telemetry:** Destination zone label, H3 index, and dropoff coordinates.
- **Financial & Routing Metrics:** Great-circle trip distance ($km$) and standard Chicago taxi fare estimate ($\$3.25 + \$1.80/\text{km}$).
- **Assigned Driver Shortcut:** Displays assigned driver ID with a one-click `View Driver →` button that immediately switches the inspection panel to driver telemetry.

---

## 5. Bidirectional Driver & Trip Linking

When inspecting a driver in the **Driver Telemetry Card**:
- Current state, vehicle speed ($32.0\text{ km/h}$), and coordinates.
- Current zone and assigned destination zone.
- Progress bar and estimated seconds remaining ($ETA$).
- Completed rides counter.
- **Active Trip Shortcut:** If the driver is assigned to a customer trip (`TO_PICKUP` or `WITH_PASSENGER`), an `Active Trip: REQ-xxxx` row appears with a `View Trip →` button that seamlessly navigates to the trip's telemetry.

---

## 6. Verification & Test Evidence

### 6.1 Frontend Test Suite (`frontend/test/*.test.js`)
Real terminal execution:
```text
> frontend@0.0.0 test
> node --test test/*.test.js

✔ formatChicagoTime converts UTC to Chicago Daylight Time (CDT) (70.9403ms)
✔ formatChicagoTimeOnly formats time portion in America/Chicago (1.2773ms)
✔ formatChicagoTime handles empty, null and invalid inputs gracefully (0.4013ms)
✔ ApiError preserves HTTP status and payload detail (1.8343ms)
✔ chicagoH3Zones.json contains exactly 239 Resolution 8 features (1.4098ms)
✔ every feature in chicagoH3Zones has valid geometry and closed polygon ring (3.788ms)
✔ every feature in chicagoH3Zones has canonical properties matching zone catalog (0.9415ms)
✔ heatmap tier thresholds map demand accurately (0.3999ms)
✔ Overview chart data transformation preserves fractional predicted demand for Zone Z-005 (2.2875ms)
✔ Overview shortage sort correctly prioritizes NO_CAPACITY deficits over surplus zones (0.3286ms)
✔ driver status colors map to canonical palette (2.0948ms)
✔ fleet conservation invariant holds across driver states (0.4717ms)
✔ dispatch summary accounting verifies coverage and assignments (0.3263ms)
✔ simulation speed multipliers map to expected interval milliseconds (0.2469ms)
✔ customer trips breakdown correctly tabulates unserved and in-transit requests (0.5004ms)
✔ in-flight stepping guard prevents concurrent step executions (0.3107ms)
✔ dynamic capacity and pressure calculation with live simulation vehicles (0.2923ms)
✔ getZoneLabel returns deterministic friendly label for known cell (1.1901ms)
✔ getZoneLabel handles null, undefined and unknown gracefully (0.2426ms)
✔ getZoneDetails returns valid coordinates and resolution (0.33ms)
✔ getAllZoneLabels returns all 239 catalog entries sorted (0.2175ms)
ℹ tests 21
ℹ suites 0
ℹ pass 21
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 221.9238
```

### 6.2 Frontend Production Build (`npm run build`)
Real terminal execution:
```text
> frontend@0.0.0 build
> vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 2497 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                 0.78 kB │ gzip:   0.37 kB
dist/assets/index-BxEpkhKL.css                 67.67 kB │ gzip:  15.58 kB
dist/assets/rolldown-runtime-hePW80VL.js        0.71 kB │ gzip:   0.42 kB
dist/assets/api-Cwh-dk4z.js                     5.54 kB │ gzip:   2.16 kB
dist/assets/SurgeAlertsView-BsnEw3m3.js         6.52 kB │ gzip:   2.11 kB
dist/assets/ZoneIntelligenceView-DnDpj_R8.js    8.52 kB │ gzip:   2.62 kB
dist/assets/ModelPerformanceView-DRXd6DOm.js    9.75 kB │ gzip:   2.47 kB
dist/assets/SystemStatusView-C_G0Lx0j.js       12.62 kB │ gzip:   3.14 kB
dist/assets/vendor-icons-CWFtkZIe.js           13.39 kB │ gzip:   5.07 kB
dist/assets/index-C-xbdfUh.js                 265.54 kB │ gzip:  79.35 kB
dist/assets/ChicagoMapView-D8coGSj-.js        274.71 kB │ gzip:  69.48 kB
dist/assets/vendor-charts-DdmkzTbP.js         382.05 kB │ gzip: 110.15 kB

✓ built in 1.46s
```

### 6.3 Backend Test Suite (`pytest`)
Real terminal execution:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2
collected 132 items

tests\integration\test_streaming_pipeline.py ss                          [  1%]
tests\unit\test_api_forecasts.py .........                               [  8%]
tests\unit\test_api_health.py ....                                       [ 11%]
tests\unit\test_api_immutability.py .                                    [ 12%]
tests\unit\test_api_metrics.py ....                                      [ 15%]
tests\unit\test_api_pressure.py ..........                               [ 22%]
tests\unit\test_api_surge.py ......                                      [ 27%]
tests\unit\test_clean_pipeline.py ......                                 [ 31%]
tests\unit\test_cleaning_policy.py ........                              [ 37%]
tests\unit\test_fleet_simulation.py ...........                          [ 46%]
tests\unit\test_forecasting_aggregation.py ......                        [ 50%]
tests\unit\test_forecasting_baselines.py ..                              [ 52%]
tests\unit\test_forecasting_evaluate.py ...                              [ 54%]
tests\unit\test_forecasting_features.py ...                              [ 56%]
tests\unit\test_forecasting_model.py ..                                  [ 58%]
tests\unit\test_forecasting_pipeline_job.py .                            [ 59%]
tests\unit\test_h3_comparison.py ....                                    [ 62%]
tests\unit\test_h3_index.py .......                                      [ 67%]
tests\unit\test_phase4_pipeline_job.py .                                 [ 68%]
tests\unit\test_pressure_and_surge.py .....                              [ 71%]
tests\unit\test_profile_raw.py ......                                    [ 76%]
tests\unit\test_streaming_consumer.py .....                              [ 80%]
tests\unit\test_streaming_contract.py ...........                        [ 88%]
tests\unit\test_streaming_producer.py ...                                [ 90%]
tests\unit\test_supply_simulation.py ...                                 [ 93%]
tests\unit\test_zone_universe.py .........                               [100%]

============================== warnings summary ===============================
..\..\..\AppData\Local\Programs\Python\Python313\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\91984\AppData\Local\Programs\Python\Python313\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
============ 130 passed, 2 skipped, 1 warning in 69.90s (0:01:09) =============
```

### 6.4 Artifact Immutability Verification
Real terminal execution:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
plugins: anyio-4.14.2
collected 1 item

tests\unit\test_api_immutability.py .                                    [100%]

============================== warnings summary ===============================
..\..\..\AppData\Local\Programs\Python\Python313\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\91984\AppData\Local\Programs\Python\Python313\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 1 passed, 1 warning in 2.13s =========================
```

All 11 canonical Phase 1–4 artifacts evaluated against hardcoded reference hashes:
- `data/gold/taxi_trips_h3_split.parquet`: `82f9d784a9261a86...` (MATCH)
- `data/gold/forecasting_features.parquet`: `a8ecf265eb4501a3...` (MATCH)
- `models/xgboost_demand_model.json`: `c3cf1346d0a793fc...` (MATCH)
- `data/gold/forecast_predictions.parquet`: `f3a675ce08ce69ba...` (MATCH)
- `data/gold/forecast_evaluation_metrics.parquet`: `75ee9a3d4f8fc1fa...` (MATCH)
- `data/gold/supply_estimates.parquet`: `5898d248eb3a7764...` (MATCH)
- `data/gold/demand_supply_pressure.parquet`: `704c7d0e4fbc5122...` (MATCH)
- `data/gold/surge_alerts.parquet`: `47ba1b671a55f694...` (MATCH)
- `data/gold/phase4_metrics.parquet`: `96c818817a0aee9e...` (MATCH)
- `data/gold/zone_universe.parquet`: `a0cbdbfe74278a9c...` (MATCH)
- `contracts/canonical_catalog.parquet`: `747fa8c02c2e0b5a...` (MATCH)

---

## 7. Operational Labeling Summary

| Entity / Metric | Label | Description |
| :--- | :---: | :--- |
| Forecast Demand ($D$) | `PREDICTED` | Supervised XGBoost model predictions on held-out test split. |
| Baseline Demand | `ESTIMATED` | Historic Naive and Moving Average comparison baselines. |
| Fleet Vehicles ($N=60$) | `SIMULATED` | In-memory physics simulation of 60 conserved commercial vehicles. |
| Vehicle Kinematics | `SIMULATED` | Haversine trajectory interpolation at $32.0\text{ km/h}$. |
| Customer Trips | `SIMULATED` | Passenger ride requests matched to closest idle vehicles. |
| Zone Capacity ($C$) | `ESTIMATED` | $C = V_{idle} \times 2.0$ rides / vehicle / 30 minutes. |
| Zone Shortage | `ESTIMATED` | $\max(0, D - C)$ unserved demand rides. |
| Test Split Observations | `HISTORICAL` | Ground truth actual rides from June 2022 City of Chicago data. |

---

## 8. Final Verdict & Limitations Statement

### Final Verdict: **PASS WITH LIMITATIONS**

**Verified Capabilities:**
- Full simulation controls implemented and operational: Start, Pause, Resume, Reset, Speed Multipliers (`0.5x`, `1x`, `2x`, `4x`), and manual Single Step.
- Safe stepping guard (`isSteppingRef`) prevents concurrent in-flight requests and eliminates clock drift.
- Live Operations KPI Bar displays authoritative fleet state with explicit 100% conservation reconciliation ($N=60$).
- Customer ride request markers (`[P]`, `[D]`) render on map with toggle control and interactive selection.
- Customer Trip Telemetry card and Driver Telemetry card are bidirectionally linked.
- 21 frontend node unit tests passing; 130 backend pytest tests passing; Vite production bundle builds cleanly in 1.46s.
- 11 canonical Phase 1–4 artifacts verified 100% invariant.

**Documented Limitations:**
1. **Live Kafka Broker:** 2 integration tests (`test_streaming_pipeline.py`) remain intentionally skipped due to absent local Kafka infrastructure on the Windows host.
2. **Interactive Browser Automation:** Chrome/Playwright drivers are not provisioned in this environment; UI integration verified via Node test suites, API contracts, and Vite compilation.
3. **Linear Trajectories:** Kinematics interpolate spatially along great-circle coordinates; real Chicago street graph routing is out of scope for this prototype.

