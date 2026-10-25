# RideIntel Phase 3 — Demand Forecasting and Baseline Models Implementation Plan

**Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand Analysis  
**Phase:** Phase 3 (Demand Forecasting, Baselines, and Evaluation)  
**Author:** Lead Data & ML Engineer  

---

## 1. Executive Objective

Phase 3 implements the demand forecasting subsystem for RideIntel. At any prediction origin $T$ on a 15-minute time grid, the system predicts the total number of ride pickups in each eligible H3 Resolution 8 spatial zone over the forward 30-minute horizon $[T, T + 30\text{ minutes})$.

The implementation rigorously adheres to:
1. **Strict Temporal Integrity:** Chronological splits only; no lookahead in feature generation or zone eligibility.
2. **Explicit Window Completeness:** Missing or unobserved 15-minute windows are never silently treated as zero; zero-filling occurs only for verified complete windows against the training-qualified zone universe.
3. **Identical-Row Evaluation:** XGBoost and both baseline models are scored on the exact same $(T, \text{zone})$ test rows.
4. **Preservation of Phase 1 & 2 Artifacts:** Phase 1 datasets and schemas remain immutable.

---

## 2. Target Variable & Horizon Definition

* **Time Grid:** Tumbling 15-minute boundaries aligned with UTC clock: $T \in \{00:00, 00:15, 00:30, 00:45\}$.
* **Prediction Origin ($T$):** The point in time at which the forecast is generated. All features must be derived strictly from historical events observed at or before $T$ ($t_{\text{event}} \le T$).
* **Target Interval:** Half-open interval $[T, T + 30\text{ minutes})$.
* **Target Definition ($Y_{z, T}$):**
  $$Y_{z, T} = \sum_{t \in [T, T + 30\text{m})} \text{rides}(z, t) = \text{ride\_count}(z, [T, T + 15\text{m})) + \text{ride\_count}(z, [T + 15\text{m}, T + 30\text{m}))$$
  where $\text{ride\_count}(z, W)$ is the zero-filled demand for eligible zone $z$ in complete 15-minute window $W$.
* **Value Constraint:** $Y_{z, T} \ge 0$, integer count.

---

## 3. Temporal Splits & Leakage Safeguards

### 3.1 Dataset Period & Split Boundaries
The cleaned dataset spans exactly 30 days:
`[2022-06-01T05:00:00Z, 2022-07-01T05:00:00Z)` = `[2022-06-01 00:00 CDT, 2022-07-01 00:00 CDT)`.

Preserving the established CDT-aligned split at `2022-06-22T05:00:00Z`:
1. **Training Partition:** `[2022-06-01T05:00:00Z, 2022-06-15T05:00:00Z)` (Days 1–14, 14 days = 336 hours = 1,344 fifteen-minute windows).
2. **Validation Partition:** `[2022-06-15T05:00:00Z, 2022-06-22T05:00:00Z)` (Days 15–21, 7 days = 168 hours = 672 fifteen-minute windows).
3. **Test Partition:** `[2022-06-22T05:00:00Z, 2022-07-01T05:00:00Z)` (Days 22–30, 9 days = 216 hours = 864 fifteen-minute windows).

### 3.2 Target Lookahead Boundary on Test Set
For origin $T$, target window requires $[T, T + 30\text{m})$.
The dataset ends at `2022-07-01T05:00:00Z`. The latest test origin $T_{\text{last}}$ with a complete 30-minute target window is `2022-07-01T04:30:00Z`. Any origin after 04:30 has an incomplete target window and must be excluded.

### 3.3 Zone Eligibility Policy (Leakage-Safe)
* **The Leakage Risk:** In Phase 1 Task 6, 139 zones had $\ge 10$ trips across the full month. However, 4 of those zones (`882664528bfffff`, `882664cf4bfffff`, `882664d89dfffff`, `882664d8d5fffff`) had $< 10$ trips during the training period and only qualified due to future test data.
* **The Policy:** Zone eligibility for model training, zero-filling, and test evaluation is derived strictly from data prior to the split ($t < \text{2022-06-22T05:00:00Z}$). Exactly **135 zones** meet the $\ge 10$ trip threshold in this period. The 4 leaked zones are classified as non-operational during the historical test evaluation.

---

## 4. Window Completeness & Zero-Filling Policy

1. **Window Completeness:** A 15-minute time grid spanning the full 30-day period contains $30 \times 24 \times 4 = 2,880$ tumbling windows.
2. **Missing vs. Zero:** In raw historical trips, lack of a record in a window is not assumed zero until validated against the window time grid. Only windows within the valid continuous collection interval $[T_{\text{start}}, T_{\text{end}}]$ are deemed complete.
3. **Deterministic Zero-Filling:** For every complete window $W$ and every zone $z \in \text{eligible\_zones}$ (135 zones):
   * If $(W, z)$ exists in aggregated trips, `ride_count = observed_count`.
   * If $(W, z)$ is absent, `ride_count = 0` with status `IMPUTED_ZERO_COMPLETE_WINDOW`.
   * Non-eligible zones are never zero-filled and never included in the forecasting matrix.

---

## 5. Feature Engineering Contract

All features for origin $T$ use only observations from $t \le T$:

| Feature Name | Type | Historical Window Used | Description |
| :--- | :--- | :--- | :--- |
| `lag_15m` | float64 | $[T - 15\text{m}, T)$ | Demand in the immediate prior 15-minute window |
| `lag_30m` | float64 | $[T - 30\text{m}, T - 15\text{m})$ | Demand 15–30 minutes prior |
| `lag_45m` | float64 | $[T - 45\text{m}, T - 30\text{m})$ | Demand 30–45 minutes prior |
| `lag_60m` | float64 | $[T - 60\text{m}, T - 45\text{m})$ | Demand 45–60 minutes prior |
| `demand_prev_30m` | float64 | $[T - 30\text{m}, T)$ | Sum of previous two 15-minute windows |
| `rolling_mean_1h` | float64 | $[T - 60\text{m}, T)$ | Mean 15-minute demand over past 1 hour (4 windows) |
| `rolling_mean_4h` | float64 | $[T - 4\text{h}, T)$ | Mean 15-minute demand over past 4 hours (16 windows) |
| `rolling_std_4h` | float64 | $[T - 4\text{h}, T)$ | Standard deviation over past 4 hours |
| `lag_24h` | float64 | $[T - 24\text{h}, T - 24\text{h} + 30\text{m})$ | Target demand at the same time yesterday |
| `lag_7d` | float64 | $[T - 7\text{d}, T - 7\text{d} + 30\text{m})$ | Target demand at the same time last week |
| `hour_of_day_local`| int32 | Derived from $T$ | Local Chicago hour of day (0–23) |
| `day_of_week_local` | int32 | Derived from $T$ | Local Chicago day of week (0=Mon, 6=Sun) |
| `is_weekend` | int32 | Derived from $T$ | 1 if Saturday or Sunday, else 0 |
| `sin_hour`, `cos_hour` | float64 | Derived from $T$ | Cyclical encoding of local hour of day |
| `zone_historical_mean`| float64 | Train only | Historical average 30m demand per zone (fitted on train only) |

### No-Lookahead Guarantee
A dedicated unit test `test_features_no_lookahead` verifies that mutating or deleting records occurring after $T$ produces identical feature vectors for origin $T$.

---

## 6. Models & Baseline Specifications

### Model 1: Previous-Window Baseline (`baseline_rolling_avg`)
* **Formula:** $\hat{Y}_{z, T} = \text{demand\_prev\_30m} = \text{ride\_count}(z, [T - 30\text{m}, T - 15\text{m})) + \text{ride\_count}(z, [T - 15\text{m}, T))$.
* **Lookback Requirement:** Exactly 30 minutes prior to $T$.
* **Rationale:** Direct naive assumption that demand over the next 30 minutes will equal the most recent 30 minutes.

### Model 2: Seasonal-Naive Baseline (`baseline_same_time_last_week`)
* **Formula:** $\hat{Y}_{z, T} = \text{ride\_count}(z, [T - 7\text{d}, T - 7\text{d} + 30\text{m}))$.
* **Lookback Requirement:** Exactly 7 days prior to $T$.
* **Rationale:** Standard benchmark capturing weekly circadian commute patterns. Requires $T \ge T_{\text{start}} + 7\text{ days}$.

### Model 3: XGBoost Regressor (`xgboost`)
* **Algorithm:** Gradient boosted decision trees (`xgboost.XGBRegressor`).
* **Objective:** `reg:squarederror` or `reg:tweedie` (handling zero-inflated Poisson-like count data).
* **Fitting Rule:** Trained strictly on Training partition; hyperparameters tuned on Validation partition. Final Test set is touched only once for evaluation.

---

## 7. Identical-Row Evaluation Contract

Per `contracts/parquet_schemas.md` (Table 4) and `AGENTS.md`:
* **Evaluation Set:** The intersection of test $(T, z)$ observations for which **all three models** have valid predictions. Because the seasonal-naive baseline requires 7 days of history, test origins from `2022-06-22T05:00:00Z` to `2022-07-01T04:30:00Z` have complete 7-day lookback (since training began on June 1, 21 days prior).
* **Metrics:**
  * **MAE:** $\frac{1}{N} \sum |Y - \hat{Y}|$
  * **RMSE:** $\sqrt{\frac{1}{N} \sum (Y - \hat{Y})^2}$
  * **WAPE:** $\frac{\sum |Y - \hat{Y}|}{\sum Y}$
  * **WAPE Zero Rule:** If $\sum Y = 0$, `wape = null` and `wape_status = "UNDEFINED_ZERO_ACTUAL"`.
* **Breakdowns:**
  * Overall performance across all test instances.
  * By zone volume category: High-volume (top 20% by historical trips), Medium-volume, Low-volume.
  * By hour of day (0–23 in local Chicago time).

---

## 8. Proposed Code Architecture

```
pipeline/forecasting/
├── __init__.py
├── aggregation.py      # 15-min window aggregations, completeness policy, zero-filling
├── eligibility.py      # Historical training-window zone eligibility (135 zones)
├── features.py         # Leakage-safe feature extraction at origin T
├── baselines.py        # Previous-window and seasonal-naive baselines
├── model.py            # XGBoost training, hyperparameter validation, inference
├── evaluate.py         # Identical-row evaluation metrics (MAE, RMSE, WAPE)
└── job.py              # End-to-end execution, Parquet artifact generation

tests/unit/
├── test_forecasting_aggregation.py
├── test_forecasting_features.py
├── test_forecasting_baselines.py
├── test_forecasting_model.py
└── test_forecasting_evaluate.py

data/processed/forecasts/
├── forecasts.parquet           # Conforms to Table 3 (forecasts)
└── forecast_evaluation.parquet # Conforms to Table 4 (forecast_evaluation)

models/
└── xgboost_demand_model.json   # Serialized reproducible model artifact
```

---

## 9. Next Steps
1. Implement `pipeline/forecasting/aggregation.py` and `pipeline/forecasting/eligibility.py` with unit tests.
2. Implement `pipeline/forecasting/features.py` with strict no-lookahead test.
3. Implement `pipeline/forecasting/baselines.py` and `pipeline/forecasting/model.py`.
4. Implement `pipeline/forecasting/evaluate.py` and `pipeline/forecasting/job.py`.
5. Execute end-to-end forecasting pipeline, run full test suite, verify Phase 1 hashes, and compile `reports/phase3_implementation_report.md`.

