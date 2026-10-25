# RideIntel H3 Resolution Evaluation & Selection Evidence

**Dataset:** Chicago Historical Taxi Trips (`wrvz-psew`, June 2022 slice)  
**Cleaned Input Rows:** 584,001 records  
**Unique Source Coordinates:** 317 census tract / community centroids  
**Evaluation Date:** 2026-10-11  
**Status:** **SELECTED_FOR_MVP** (Selected: **Resolution 8**)  
**Configured Path:** `settings.yaml` (`h3.resolution: 8`)

---

## 1. Candidate Resolutions Comparison Table

| Metric | Resolution 7 | Resolution 8 (Selected) | Resolution 9 |
| :--- | :--- | :--- | :--- |
| **Hexagon Area (approx)** | ~5.16 km² | **~0.74 km²** | ~0.11 km² |
| **Hexagon Edge Length** | ~1.22 km | **~461 m** (~4-5 city blocks) | ~174 m |
| **Scale Description** | Macro-neighborhood | **Urban district / catchment** | Micro-block |
| **Eligible Trips Indexed** | 584,001 | **584,001** | 584,001 |
| **Skipped / Invalid Trips** | 0 | **0** | 0 |
| **Distinct Occupied Cells** | 103 | **239** | 312 |
| **Median Trips / Cell** | 441.0 | **40.0** | 14.0 |
| **P90 Trips / Cell** | 9,187.2 | **3,503.8** | 3,310.4 |
| **P95 Trips / Cell** | 21,810.8 | **13,099.1** | 9,052.9 |
| **Maximum Trips in a Cell** | 183,941 (31.5%) | **66,000 (11.3%)** | 60,943 (10.4%) |
| **Cells < 10 trips (Descriptive)** | 14 (13.59%) | **100 (41.84%)** | 147 (47.12%) |
| **Cells < 50 trips** | 24 (23.30%) | **126 (52.72%)** | 200 (64.10%) |
| **Top 5 Cells Share** | 65.65% | **42.20%** | 37.89% |
| **Top 10 Cells Share** | 78.78% | **61.16%** | 56.41% |
| **Indexing Runtime** | 1.9472s | **2.0133s** | 2.0394s |

> [!NOTE]
> The count of cells with fewer than 10 trips is a **descriptive distribution metric**, not a universal quality threshold. In municipal taxi datasets with central business district concentration (e.g. Loop, O'Hare), peripheral residential zones naturally exhibit low monthly hail counts.

---

## 2. Selection Rationale & Spatial Trade-Off Analysis

### The Nature of the Source Geometry
The City of Chicago Taxi Trips dataset (`wrvz-psew`) anonymizes pickup and dropoff locations to **census tract or community area centroids**. In June 2022, there are exactly **317 unique coordinate pairs** across all 584,001 trips.

### Trade-Off Evaluation

#### Resolution 7 (~5.16 km²): Over-Aggregated
- **Limitation:** At Resolution 7, multiple census tracts are merged into single broad cells. The single busiest cell absorbs **183,941 trips** (31.5% of the city total).
- **Impact:** Obscures demand dynamics between high-density adjacent neighborhoods (e.g., merging the Loop, West Loop, and Near North into one massive cell). Supply simulation and dispatch pressure cannot provide localized guidance at this macro scale.

#### Resolution 9 (~0.11 km², ~174m edge length): False Precision & Extreme Sparsity
- **Limitation:** The 174-meter hexagon radius is substantially smaller than the census tracts that produced the 317 source centroids. Mapping aggregated tract centroids to 174m hexes imposes an illusion of street-block precision that does not exist in the source data.
- **Impact:** High temporal sparsity. The median trips per cell across the entire month is only **14 trips** (<0.5 trips/day). In downstream 15-minute streaming windows, the vast majority of cells would be empty, causing severe zero-inflation for forecasting models.

#### Resolution 8 (~0.74 km², ~461m edge length): Optimal MVP Resolution
- **Granularity:** Resolves the 317 source tract centroids into **239 distinct operational cells**. Hexagons of ~461m radius (~4–5 city blocks) correspond to standard urban taxi stands, pedestrian walking buffers, and ride-hail pickup zones.
- **Demand Density:** Core demand centers maintain substantial trip volume for 15-minute time aggregation (top cell: 66,000 trips/month; 90th percentile: 3,504 trips/month).
- **Alignment with Industry Standards:** Resolution 8 is Uber's documented standard resolution for city-wide ride-hail marketplace modeling and dispatch pressure analysis.

---

## 3. Geographic Sanity Checks

1. **Determinism:** Verified. The exact same coordinate pair deterministically maps to the exact same H3 cell index across repeated evaluations.
2. **Reconciliation:** Exactly 584,001 eligible rows were indexed with 0 skipped or invalid coordinates.
3. **326 O'Hare Border Records:** The 326 records with valid coordinates (`41.982775009, -87.8773054`) and missing community area map cleanly to a single valid H3 cell (`882664c1a9fffff` at Res 8). No community area ID was fabricated.
4. **Non-Additivity:** H3 gridded demand (584,001 eligible rows) and Community Area administrative rollups (583,675 eligible rows) remain separate, parallel perspectives.
5. **Exclusion Isolation:** All 55,268 records excluded for lacking all spatial references remain isolated in `data/interim/excluded_trips_2022-06/excluded_trips.parquet` and were not indexed.

---

## 4. Configuration Update

The selected resolution is configured in `settings.yaml`:
```yaml
h3:
  resolution: 8            # SELECTED in Phase 1 Task 5 (H3 Resolution Comparison)
```
