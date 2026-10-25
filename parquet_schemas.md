# Parquet schemas  (STATUS: DRAFT v0.1, freeze after dataset inspection)

All timestamps: UTC, timezone-aware (`timestamp[us, tz=UTC]`). Display conversion happens only in the frontend.
Column names are exact. Do not rename without changing this file first.

## 1. demand_windows  (Spark output, observed demand)
| column | type | null | notes |
|---|---|---|---|
| h3_cell | string | no | H3 cell at the configured resolution |
| window_start | timestamp | no | inclusive |
| window_end | timestamp | no | = window_start + 15 min |
| ride_count | int64 | no | > 0. Only observed windows are written |
| dataset_type | string | no | HISTORICAL_REPLAY or SIMULATED |
| processing_run_id | string | no | isolates experiments |

* Absent zone-window is **not** a confirmed zero. Zero-filling happens only downstream, against `zone_universe`, and only for complete windows.
* Stream output contains finalized windows only (append mode). Late events beyond the watermark are dropped by streaming and kept by batch; every batch/stream difference must be explained.
* Deduplication horizon = watermark. A duplicate arriving after its dedup state expired may be counted again. This is documented behaviour, tested both inside and beyond the horizon.

## 2. zone_universe  (defined once, used for zero-filling and evaluation)
| column | type | notes |
|---|---|---|
| h3_cell | string | zones eligible for forecasting |
| rule | string | how it was chosen (e.g. "cells with >= N rides in training period") |

## 3. forecasts  (append only, never overwritten)
| column | type | null | notes |
|---|---|---|---|
| forecast_id | string | no | unique |
| h3_cell | string | no | |
| forecast_origin | timestamp | no | T; only data before T is used for features |
| target_start | timestamp | no | = T |
| target_end | timestamp | no | = T + 30 min |
| predicted_rides | float64 | no | >= 0 (document any clipping rule) |
| model_name | string | no | `xgboost`, `baseline_rolling_avg`, `baseline_same_time_last_week` |
| model_version | string | no | |
| forecast_status | string | no | `CURRENT`, `STALE_AFTER_SURGE`, `SUPERSEDED` |
| processing_run_id | string | no | |

`STALE_AFTER_SURGE` is a status flag only. The original prediction stays unchanged.

## 4. forecast_evaluation  (one row per origin x zone x model, held-out test only)
| column | type | null | notes |
|---|---|---|---|
| h3_cell | string | no | |
| forecast_origin | timestamp | no | |
| target_start / target_end | timestamp | no | |
| model_name / model_version | string | no | |
| predicted_rides | float64 | no | |
| actual_rides | int64 | no | counted from complete windows, zero-filled against zone_universe |
| split | string | no | always `test` here |

Rules:
* XGBoost and **both** baselines are scored on the **identical** set of (origin, zone) rows. Use the intersection of rows every model can predict (e.g. same-time-last-week needs history) and record how many rows were excluded and why.
* Metrics: MAE, RMSE, WAPE. WAPE = sum|actual - predicted| / sum(actual).
* **If sum(actual) = 0, WAPE is undefined**: write `wape = null` and `wape_status = "UNDEFINED_ZERO_ACTUAL"`. Never write 0 or invent a value.
* Report overall, by zone-density group, by hour of day, and the exact test interval and row count.

## 5. vehicle_snapshots  (simulated, seeded)
| column | type | null | notes |
|---|---|---|---|
| vehicle_id | string | no | |
| snapshot_ts | timestamp | no | simulation time, UTC |
| lat / lon | float64 | no | inside configured city bounds |
| h3_cell | string | no | |
| status | string | no | AVAILABLE, BUSY, OFFLINE |
| simulation_run_id | string | no | |
| source_type | string | no | always SIMULATED |

## 6. zone_status  (estimated pressure; written by ml/supply.py)
| column | type | null | notes |
|---|---|---|---|
| h3_cell | string | no | |
| as_of | timestamp | no | simulation time |
| predicted_rides_D | float64 | yes | null when no valid forecast |
| available_vehicles_V | int64 | yes | only status AVAILABLE in this cell at snapshot time |
| capacity_rate_r | float64 | no | from config, scenario assumption |
| estimated_capacity_C | float64 | yes | C = V x r |
| pressure_index | float64 | yes | **null** when C = 0 or input unknown. Never infinity |
| pressure_status | string | no | see below |
| input_status | string | no | `OK`, `MISSING`, `STALE` |

### Pressure rules (evaluated in this order)
1. `input_status` is `MISSING` or `STALE` -> `UNKNOWN`, index null.
2. C = 0 and D > 0 -> `NO_ESTIMATED_CAPACITY`, index null.
3. C = 0 and D = 0 -> `NORMAL`, index 0.
4. C > 0: P = D / C, then P > high_ratio -> `HIGH_PRESSURE`; P >= elevated_ratio -> `ELEVATED`; else `NORMAL`.

Status and numeric index are separate fields. The index is an **estimated pressure index** (scenario-based decision support), not real-world utilization.

## 7. surge_alerts
| column | type | null | notes |
|---|---|---|---|
| alert_id | string | no | |
| h3_cell | string | no | |
| detected_at | timestamp | no | |
| observed_demand | int64 | no | |
| baseline_demand | float64 | yes | null if baseline too small to be stable |
| severity | string | no | |
| simulation_run_id | string | no | |
