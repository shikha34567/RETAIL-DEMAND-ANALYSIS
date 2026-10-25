# RideIntel Operational Zone Universe Specification & Rule Analysis

**Dataset:** Chicago Historical Taxi Trips (`wrvz-psew`, June 2022 slice)  
**Total Coordinate-Eligible Trips:** 584,001 [HISTORICAL]  
**Distinct Occupied H3 Cells (Res 8):** 239 zones  
**Operational Rule:** `MIN_HISTORICAL_TRIPS_10` (Historical Pickups >= 10) [PROVISIONAL OPERATIONAL CHOICE]  
**Retained Operational Zones:** **139 zones** (58.16%)  
**Retained Historical Volume:** **583,659 trips** (**99.9414%** coverage)  
**Excluded Dormant Zones:** 100 zones (342 trips, 0.0586%)

---

## 1. Candidate Rule Threshold Comparison

| Minimum Trips Rule | Operational Zones | Dropped Zones | Retained Trips | Dropped Trips | Trip Volume Coverage | Operational Assessment |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **All Observed (>= 1)** | 239 (100.0%) | 0 (0.0%) | 584,001 | 0 | 100.000% | Comprehensive catalog of all observed cells; includes sparse peripheral zones (monthly counts alone do not establish window-level zero percentages without window completeness validation). |
| **>= 2 Trips** | 217 (90.8%) | 22 (9.2%) | 583,979 | 22 | 99.996% | Drops only single-trip isolated outliers. |
| **>= 5 Trips** | 165 (69.0%) | 74 (31.0%) | 583,835 | 166 | 99.972% | Retains moderate coverage; some sporadic zones remain. |
| **>= 10 Trips (PROVISIONAL)** | **139 (58.2%)** | **100 (41.8%)** | **583,659** | **342** | **99.941%** | **Provisional operational choice:** Filters 100 low-volume zones (<10 trips across full month) while retaining 99.94% of observed historical trips. Provisional pending forecasting evaluation. |
| **>= 25 Trips** | 126 (52.7%) | 113 (47.3%) | 583,467 | 534 | 99.909% | Begins excluding emerging neighborhood commercial clusters. |
| **>= 50 Trips** | 117 (49.0%) | 122 (51.0%) | 583,161 | 840 | 99.856% | Excludes 22 viable residential pickup zones. |
| **>= 100 Trips** | 106 (44.4%) | 133 (55.6%) | 582,362 | 1,639 | 99.719% | Core downtown/airport only; eliminates 33 active neighborhood corridors. |

---

## 2. Selection Rationale for Provisional Rule `MIN_HISTORICAL_TRIPS_10`

### Purpose and Justification
The operational zone universe is defined as a **provisional operational choice** for historical activity filtering. It serves two architectural functions:
1. **Downstream Zero-Filling Boundary:** As specified in `parquet_schemas.md` and `AGENTS.md`, missing data is **not** zero. Incomplete windows are never zero-filled; complete 15-minute windows are zero-filled strictly against `zone_universe`.
2. **Forecasting Model Boundary:** Models (XGBoost and baselines) are evaluated on active operational zones.

### Why Filter Peripheral Low-Volume Zones (< 10 Trips)?
- In June 2022, 22 zones have exactly **1 single trip** in the entire month, and 100 zones have fewer than 10 trips.
- While low monthly counts imply severe temporal sparsity across 2,880 potential 15-minute windows, monthly totals alone cannot establish exact window-level zero percentages without aggregating over finalized, complete windows.
- Excluding these 100 peripheral zones discards only **342 trips across the entire month** (less than 12 trips/day citywide) while retaining **99.941% of all trips** across **139 active zones**.
- This threshold is provisional: empirical forecasting validation in Phase 3 will determine whether retaining or excluding peripheral zones impacts WAPE/MAE.

---

## 3. Temporal Eligibility: Retrospective vs. Evaluation-Safe

### Dataset Interval (Half-Open)
The cleaned dataset covers the half-open UTC interval:

`[2022-06-01T05:00:00Z, 2022-07-01T05:00:00Z)` = `[2022-06-01 00:00 CDT, 2022-07-01 00:00 CDT)`

**Total duration:** exactly 30 days (720 hours).

### `is_operational_universe` Column Scope

> **WARNING:** The `is_operational_universe` column in `zone_universe.parquet` reflects **full-month June 2022 retrospective status**. It must NOT be treated as leakage-safe eligibility for chronological forecasting evaluation. Phase 3 must derive training-window eligibility independently.

### Temporal Leakage Demonstration
Using a CDT-aligned chronological split at `2022-06-22T05:00:00Z` (= midnight CDT June 22):
- **Training partition:** `[2022-06-01T05:00:00Z, 2022-06-22T05:00:00Z)` = exactly **21 local days**
- **Test partition:** `[2022-06-22T05:00:00Z, 2022-07-01T05:00:00Z)` = exactly **9 local days**
- **Training-only operational zones (t < split):** **135 zones** meet the >= 10 trip threshold.
- **Full-month operational zones:** **139 zones** meet the threshold.
- **Leaked zones (4 zones):** `882664528bfffff, 882664cf4bfffff, 882664d89dfffff, 882664d8d5fffff` had < 10 trips during the training period and only reached >= 10 trips due to test-period volume.

| Leaked Zone | Training Trips | Full-Month Trips |
| :--- | :--- | :--- |
| `882664528bfffff` | 7 | 10 |
| `882664cf4bfffff` | 8 | 14 |
| `882664d89dfffff` | 7 | 15 |
| `882664d8d5fffff` | 5 | 11 |

### Phase 3 Contract Rule
> **In Phase 3 forecasting, operational zone eligibility must be determined strictly within the training window (t < T_split).** Any evaluation on test data must use zones qualified prior to the split time.

### Downstream Handling of Non-Eligible Zones (Phase 3)
- **Zones in training eligibility set:** Included in zero-filling, model training, and evaluation for that split.
- **Zones absent from training eligibility set:** Excluded from zero-filling and model evaluation. Predictions are not generated. Dashboard shows `NON_OPERATIONAL` or omits them from the forecasting grid.
- **Catalog preservation:** All 239 observed cells remain in `zone_universe.parquet` as a historical reference catalog regardless of split-specific eligibility.

---

## 4. Distribution of Historical Trips Across Retained Zones

Across the **139 operational zones** (full-month retrospective):
- **Minimum:** 10 trips
- **10th Percentile (P10):** 25.8 trips
- **25th Percentile (P25):** 111.5 trips
- **Median (P50):** 436.0 trips
- **75th Percentile (P75):** 2070.0 trips
- **90th Percentile (P90):** 8980.600000000004 trips
- **95th Percentile (P95):** 22153.999999999993 trips
- **Maximum:** 66,000 trips (Near North Side / River North: `882664c1edfffff`)
- **Mean:** 4198.99 trips (Standard Deviation: 11020.83)

---

## 5. Zero-Observation and Missing Data Strategy

Per the RideIntel data contract:
1. **Streaming / Ingestion:** Spark writes finalized windows in append mode containing observed demand only (`ride_count > 0`). An absent zone-window is never treated as a confirmed zero.
2. **Feature Engineering & ML Training:** Downstream feature pipelines join complete historical windows against the operational zones in `zone_universe`. Absent complete windows for operational zones are deterministically zero-filled to `ride_count = 0`.
3. **Dashboard & API (`/api/zones`):**
   - Operational zones with 0 observed rides display `observed_rides = 0`.
   - Zones with 0 predicted demand and 0 estimated capacity (D=0, C=0) trigger **Pressure Rule 3**: `pressure_status = NORMAL`, `pressure_index = 0.0`.
   - Excluded dormant zones (the 100 cells with <10 trips) are labelled `NON_OPERATIONAL` or excluded from the forecasting grid.

---

## 6. Unresolved Limitations

1. **Centroid Snapping:** Source coordinates are snapped to 317 census tract centroids. While Resolution 8 provides ~461m cells, zone boundaries in outer tracts reflect centroid clusters rather than exact street addresses.
2. **Single-Month Scope:** June 2022 reflects summer conditions. Peripheral zones that qualify in June might drop below 10 trips in January, and vice-versa. Seasonality should be re-calibrated when multi-month historical slices are incorporated.
3. **Threshold Provisional:** The 10-trip threshold remains provisional until chronological forecasting backtests evaluate alternatives.
