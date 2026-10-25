# RideIntel Phase 3 — Demand Forecasting and Baseline Models Implementation Report

**Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand Analysis  
**Phase:** Phase 3 (Demand Forecasting, Baselines, and Evaluation)  
**Author:** Lead Data & ML Engineer  
**Overall Status:** **PASS** (76 unit tests passed, 2 integration tests skipped as BLOCKED due to absent host Docker/WSL2; All Phase 1 hashes invariant).

---

## 1. Executive Summary

Phase 3 implements the demand forecasting and baseline evaluation subsystem for RideIntel. At each prediction origin $T$ on a tumbling 15-minute time grid, the system predicts the total number of ride pickups in each eligible H3 Resolution 8 spatial zone over the forward 30-minute horizon $[T, T + 30\text{ minutes})$.

The pipeline was executed end-to-end on the cleaned historical Chicago taxi dataset (`cleaned_trips.parquet`, 584,001 trips). Operational zone eligibility was established strictly using training observations ($t < \text{2022-06-22T05:00:00Z}$), identifying **135 eligible operational zones** and excluding 4 retrospective-leaked zones from model training and evaluation.

All models—**XGBoost Regressor**, **Previous-Window Baseline** (`baseline_rolling_avg`), and **Seasonal-Naive Baseline** (`baseline_same_time_last_week`)—were evaluated on the exact same **116,505 held-out test observations** across 9 days.

On the identical held-out test evaluation set:
* **XGBoost:** MAE = **0.9310**, RMSE = **2.2366**, WAPE = **31.87%**
* **Previous-Window Baseline:** MAE = **1.0990**, RMSE = **2.8157**, WAPE = **37.62%**
* **Seasonal-Naive Baseline:** MAE = **1.1907**, RMSE = **3.3163**, WAPE = **40.75%**

XGBoost achieved a **15.3% reduction in MAE** and **20.6% reduction in RMSE** over the best baseline (`baseline_rolling_avg`), and in high-density operational zones (where 89.1% of trip volume occurs), XGBoost achieved a **WAPE of 23.38%** vs. 28.75% for the previous-window baseline.

---

## 2. Target Variable & Horizon Definition

* **Time Grid:** 15-minute tumbling windows: $T \in \{00:00, 00:15, 00:30, 00:45\}$ UTC.
* **Prediction Origin ($T$):** The point in time at which the forecast is generated. Features are constructed strictly from events observed at or before $T$ ($t_{\text{event}} \le T$).
* **Target Horizon:** Forward 30-minute interval $[T, T + 30\text{ minutes})$.
* **Target Formulation ($Y_{z, T}$):**
  $$Y_{z, T} = \text{ride\_count}(z, [T, T + 15\text{m})) + \text{ride\_count}(z, [T + 15\text{m}, T + 30\text{m}))$$
  where each 15-minute window is zero-filled against the eligible zone universe.
* **Target Constraint:** $Y_{z, T} \ge 0$, integer count.

---

## 3. Temporal Split & Leakage-Safe Zone Eligibility

### 3.1 Chronological Split Boundaries
* **Dataset Period:** `[2022-06-01T05:00:00Z, 2022-07-01T05:00:00Z)` (30 full days, 720 hours).
* **Train Lookback Buffer:** `[2022-06-01T05:00:00Z, 2022-06-08T05:00:00Z)` (7 days required for `lag_7d` lookback).
* **Training Partition:** `[2022-06-08T05:00:00Z, 2022-06-15T05:00:00Z)` (7 days = 672 origins, 90,720 samples).
* **Validation Partition:** `[2022-06-15T05:00:00Z, 2022-06-22T05:00:00Z)` (7 days = 672 origins, 90,720 samples).
* **Test Partition:** `[2022-06-22T05:00:00Z, 2022-07-01T04:30:00Z]` (9 days = 863 origins, 116,505 samples).
  * *Note on Test Upper Bound:* The last valid test origin is `2022-07-01T04:30:00Z`, whose 30-minute target window $[04:30, 05:00)$ concludes at the dataset termination boundary. Origins after 04:30 are incomplete and excluded.

### 3.2 Leakage-Safe Zone Eligibility
* In Phase 1 Task 6, 139 zones had $\ge 10$ trips across the full retrospective month.
* However, 4 zones (`882664528bfffff`, `882664cf4bfffff`, `882664d89dfffff`, `882664d8d5fffff`) had $< 10$ trips during the training window and only reached the threshold due to test-period volume.
* **Enforced Policy:** Zone eligibility for training, zero-filling, and test evaluation was derived strictly within the training period ($t < \text{2022-06-22T05:00:00Z}$). Exactly **135 zones** met the $\ge 10$ trip threshold. The 4 leaked zones were classified as non-operational during historical test evaluation.

---

## 4. Window Completeness & Zero-Filling Policy

1. **Completeness Verification:** A continuous grid of 2,880 fifteen-minute tumbling windows was generated across June 2022.
2. **Missing vs. Zero:** Incomplete or out-of-boundary windows are never zero-filled. Only verified complete 15-minute windows within $[T_{\text{start}}, T_{\text{end}}]$ are zero-filled.
3. **Cartesian Zero-Filling:** For all 2,880 complete windows across all 135 training-eligible zones ($2,880 \times 135 = 388,800$ window-zone combinations):
   * If observed trips exist, `ride_count = observed_count` with status `HISTORICAL_OBSERVED`.
   * If no trips exist, `ride_count = 0` with status `ZERO_FILLED_COMPLETE_WINDOW`.

---

## 5. Feature Engineering Contract & No-Lookahead Proof

At any prediction origin $T$, all features are computed strictly from historical events with $t \le T$:

| Feature Name | Lookback Interval | Description |
| :--- | :--- | :--- |
| `lag_15m` | $[T - 15\text{m}, T)$ | Demand in immediate prior 15-minute window |
| `lag_30m` | $[T - 30\text{m}, T - 15\text{m})$ | Demand 15–30 minutes prior |
| `lag_45m` | $[T - 45\text{m}, T - 30\text{m})$ | Demand 30–45 minutes prior |
| `lag_60m` | $[T - 60\text{m}, T - 45\text{m})$ | Demand 45–60 minutes prior |
| `demand_prev_30m` | $[T - 30\text{m}, T)$ | Sum of previous two 15-minute windows |
| `rolling_mean_1h` | $[T - 60\text{m}, T)$ | Average 15-minute demand over past 1 hour |
| `rolling_mean_4h` | $[T - 4\text{h}, T)$ | Average 15-minute demand over past 4 hours |
| `rolling_std_4h` | $[T - 4\text{h}, T)$ | Standard deviation of demand over past 4 hours |
| `lag_24h` | $[T - 24\text{h}, T - 24\text{h} + 30\text{m})$ | Target demand at the same time yesterday |
| `lag_7d` | $[T - 7\text{d}, T - 7\text{d} + 30\text{m})$ | Target demand at the same time last week |
| `hour_of_day` | Derived from $T$ | Local Chicago hour of day (0–23) |
| `day_of_week` | Derived from $T$ | Local Chicago day of week (0=Mon, 6=Sun) |
| `is_weekend` | Derived from $T$ | Indicator (1 if Sat/Sun, else 0) |
| `sin_hour`, `cos_hour` | Derived from $T$ | Cyclical encoding of local hour of day |
| `zone_historical_mean`| Train only | Mean target demand for zone, fitted on training set only |

* **Empirical Verification:** The unit test `test_features_no_lookahead_contract` verified that corrupting or inserting massive future surges into $t \ge T$ resulted in byte-identical feature vectors at origin $T$.

---

## 6. Model & Baseline Specifications

### 6.1 Previous-Window Baseline (`baseline_rolling_avg`)
* **Formula:** $\hat{Y}_{z, T} = \text{ride\_count}(z, [T - 30\text{m}, T - 15\text{m})) + \text{ride\_count}(z, [T - 15\text{m}, T))$.
* **Lookback:** Exactly 30 minutes prior to $T$.

### 6.2 Seasonal-Naive Baseline (`baseline_same_time_last_week`)
* **Formula:** $\hat{Y}_{z, T} = \text{ride\_count}(z, [T - 7\text{d}, T - 7\text{d} + 30\text{m}))$.
* **Lookback:** Exactly 7 days prior to $T$.

### 6.3 XGBoost Regressor (`xgboost`)
* **Implementation:** `xgboost.XGBRegressor` (`xgboost==3.4.1`).
* **Parameters:** `n_estimators=120`, `max_depth=6`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, `objective='reg:squarederror'`.
* **Early Stopping / Validation:** Monitored against the held-out validation set (`[2022-06-15, 2022-06-22)`).
* **Prediction Constraint:** Output clipped to $\ge 0$.

---

## 7. Model Evaluation & Comparison

All models were evaluated on the exact same **116,505 held-out test rows** (863 origins $\times$ 135 eligible zones).

### 7.1 Overall Test Evaluation

| Model Name | Evaluated Rows | Sum Actual Demand | MAE | RMSE | WAPE | WAPE Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`xgboost`** | **116,505** | **340,399** | **0.9310** | **2.2366** | **31.87%** | `VALID` |
| **`baseline_rolling_avg`** | **116,505** | **340,399** | **1.0990** | **2.8157** | **37.62%** | `VALID` |
| **`baseline_same_time_last_week`** | **116,505** | **340,399** | **1.1907** | **3.3163** | **40.75%** | `VALID` |

### 7.2 Performance Breakdown by Zone Density Group

Zones were segmented into density tiers based on historical training demand:
* **High-Density (Top 20%):** 27 zones, accounting for **303,393 trips** (89.1% of test volume).
* **Medium-Density (Next 40%):** 54 zones, accounting for **33,056 trips** (9.7% of test volume).
* **Low-Density (Bottom 40%):** 54 zones, accounting for **3,950 trips** (1.2% of test volume).

| Density Group | Model Name | Evaluated Rows | Actual Volume | MAE | RMSE | WAPE |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **HIGH_DENSITY** | **XGBoost** | **23,301** | **303,393** | **3.0437** | **4.7788** | **23.38%** |
| HIGH_DENSITY | Previous-Window Baseline | 23,301 | 303,393 | 3.7439 | 5.9770 | 28.75% |
| HIGH_DENSITY | Seasonal-Naive Baseline | 23,301 | 303,393 | 4.2171 | 7.1414 | 32.39% |
| **MEDIUM_DENSITY** | **XGBoost** | **46,602** | **33,056** | **0.5518** | **1.0987** | **77.81%** |
| MEDIUM_DENSITY | Previous-Window Baseline | 46,602 | 33,056 | 0.6543 | 1.3411 | 92.27% |
| MEDIUM_DENSITY | Seasonal-Naive Baseline | 46,602 | 33,056 | 0.6481 | 1.3397 | 91.40% |
| **LOW_DENSITY** | **XGBoost** | **46,602** | **3,950** | **0.1698** | **0.4182** | **200.35%** |
| LOW_DENSITY | Previous-Window Baseline | 46,602 | 3,950 | 0.2212 | 0.4907 | 260.91% |
| LOW_DENSITY | Seasonal-Naive Baseline | 46,602 | 3,950 | 0.2198 | 0.4883 | 259.27% |

*Interpretation:* In high-volume zones where ride-hailing demand drives fleet rebalancing, XGBoost achieves a strong WAPE of 23.38% (outperforming baselines by 5.37 percentage points). In sparse low-density zones with average demand $< 0.1$ trips per 30 minutes, absolute MAE is minimal (0.17 rides), but percentage metrics (WAPE) expand due to near-zero denominators.

### 7.3 WAPE Undefined Rule Verification
In accordance with `AGENTS.md` and `contracts/parquet_schemas.md`:
* When $\sum \text{actual} = 0$, WAPE is undefined. The unit test `test_wape_undefined_zero_actual_contract` confirmed that any zero-actual evaluation returns `wape = null` and `wape_status = "UNDEFINED_ZERO_ACTUAL"`.

---

## 8. Artifacts Created & Output Locations

1. **Parquet Forecasts Table (`data/processed/forecasts/forecasts.parquet`):**
   * Conforms to `contracts/parquet_schemas.md` Table 3 (`forecasts`).
   * Contains **349,515 rows** (116,505 observations $\times$ 3 models).
   * Schema: `forecast_id`, `h3_cell`, `forecast_origin`, `target_start`, `target_end`, `predicted_rides`, `model_name`, `model_version`, `forecast_status`, `processing_run_id`.
2. **Parquet Evaluation Table (`data/processed/forecasts/forecast_evaluation.parquet`):**
   * Conforms to `contracts/parquet_schemas.md` Table 4 (`forecast_evaluation`).
   * Contains **349,515 rows**.
   * Schema: `h3_cell`, `forecast_origin`, `target_start`, `target_end`, `model_name`, `model_version`, `predicted_rides`, `actual_rides`, `split`.
3. **Serialized Trained Model (`models/xgboost_demand_model.json`):**
   * Native XGBoost JSON artifact along with metadata sidecar (`models/xgboost_demand_model.json.meta.json`).
4. **Evidence Summary (`docs/evidence/forecasting_evaluation_summary.json`):**
   * Full machine-readable evaluation report including overall metrics, density breakdown, and hourly breakdowns.

---

## 9. Test Suite Execution & Evidence

### Command:
```powershell
python -m pytest -v
```

### Actual Terminal Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\91984\AppData\Local\Programs\Python\Python313\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2
collecting ... collected 78 items

tests/integration/test_streaming_pipeline.py::test_live_kafka_broker_connectivity SKIPPED [  1%]
tests/integration/test_streaming_pipeline.py::test_e2e_streaming_pipeline_execution SKIPPED [  2%]
tests/unit/test_clean_pipeline.py::test_compute_event_id PASSED          [  3%]
tests/unit/test_clean_pipeline.py::test_timestamp_localization_and_interval PASSED [  5%]
tests/unit/test_clean_pipeline.py::test_pipeline_unit_record_evaluation PASSED [  6%]
tests/unit/test_clean_pipeline.py::test_pipeline_integration_small_dataset PASSED [  7%]
tests/unit/test_clean_pipeline.py::test_production_reports_not_polluted_by_testing PASSED [  8%]
tests/unit/test_clean_pipeline.py::test_all_exclusion_ranks_accounting_and_precedence PASSED [ 10%]
tests/unit/test_cleaning_policy.py::test_reason_codes_contract_validity PASSED [ 11%]
tests/unit/test_cleaning_policy.py::test_stable_event_id_generation PASSED [ 12%]
tests/unit/test_cleaning_policy.py::test_mutually_exclusive_geographic_partition PASSED [ 14%]
tests/unit/test_cleaning_policy.py::test_overlapping_eligibility_counts_derivation PASSED [ 15%]
tests/unit/test_cleaning_policy.py::test_reconciliation_equation PASSED  [ 16%]
tests/unit/test_cleaning_policy.py::test_quality_flags_do_not_reduce_included_count PASSED [ 17%]
tests/unit/test_cleaning_policy.py::test_primary_exclusion_precedence_logic PASSED [ 19%]
tests/unit/test_cleaning_policy.py::test_half_open_interval_boundary PASSED [ 20%]
tests/unit/test_forecasting_aggregation.py::test_floor_to_window PASSED  [ 21%]
tests/unit/test_forecasting_aggregation.py::test_window_grid_generation_full_month PASSED [ 23%]
tests/unit/test_forecasting_aggregation.py::test_is_window_complete PASSED [ 24%]
tests/unit/test_forecasting_aggregation.py::test_zero_filling_policy_on_synthetic_data PASSED [ 25%]
tests/unit/test_forecasting_aggregation.py::test_compute_target_demand_calculation PASSED [ 26%]
tests/unit/test_forecasting_aggregation.py::test_training_eligibility_derivation_real_dataset PASSED [ 28%]
tests/unit/test_forecasting_baselines.py::test_previous_window_baseline PASSED [ 29%]
tests/unit/test_forecasting_baselines.py::test_seasonal_naive_baseline PASSED [ 30%]
tests/unit/test_forecasting_evaluate.py::test_compute_metrics_standard PASSED [ 32%]
tests/unit/test_forecasting_evaluate.py::test_wape_undefined_zero_actual_contract PASSED [ 33%]
tests/unit/test_forecasting_evaluate.py::test_evaluate_models_on_identical_rows PASSED [ 34%]
tests/unit/test_forecasting_features.py::test_extract_calendar_features PASSED [ 35%]
tests/unit/test_forecasting_features.py::test_features_no_lookahead_contract PASSED [ 37%]
tests/unit/test_forecasting_features.py::test_build_full_feature_matrix_consistency PASSED [ 38%]
tests/unit/test_forecasting_model.py::test_xgboost_fit_and_predict PASSED [ 39%]
tests/unit/test_forecasting_model.py::test_xgboost_unfitted_error PASSED [ 41%]
tests/unit/test_forecasting_pipeline_job.py::test_forecasting_artifacts_exist_and_conform PASSED [ 42%]
tests/unit/test_h3_comparison.py::test_h3_resolution_metrics_metadata PASSED [ 43%]
tests/unit/test_h3_comparison.py::test_comparator_on_synthetic_dataset PASSED [ 44%]
tests/unit/test_h3_comparison.py::test_production_evidence_invariance_during_testing PASSED [ 46%]
tests/unit/test_h3_comparison.py::test_comparison_metrics_determinism PASSED [ 47%]
tests/unit/test_h3_index.py::test_validate_resolution PASSED             [ 48%]
tests/unit/test_h3_index.py::test_validate_coordinates PASSED            [ 50%]
tests/unit/test_h3_index.py::test_deterministic_output PASSED            [ 51%]
tests/unit/test_h3_index.py::test_argument_order_verification PASSED     [ 52%]
tests/unit/test_h3_index.py::test_safe_coords_to_h3_null_and_invalid_inputs PASSED [ 53%]
tests/unit/test_h3_index.py::test_strict_latlng_to_h3 PASSED             [ 55%]
tests/unit/test_ohare_border_records_indexing PASSED   [ 56%]
tests/unit/test_profile_raw.py::test_parse_float PASSED                  [ 57%]
tests/unit/test_profile_raw.py::test_parse_int PASSED                    [ 58%]
tests/unit/test_profile_raw.py::test_parse_and_localize_timestamp_chicago_to_utc PASSED [ 60%]
tests/unit/test_profile_raw.py::test_parse_and_localize_timestamp_non_aligned PASSED [ 61%]
tests/unit/test_profile_raw.py::test_parse_and_localize_timestamp_invalid PASSED [ 62%]
tests/unit/test_profile_raw.py::test_dataset_profiler_line_processing PASSED [ 64%]
tests/unit/test_streaming_consumer.py::test_spark_streaming_schema_definition PASSED [ 65%]
tests/unit/test_streaming_consumer.py::test_fifteen_minute_window_boundary_calculations PASSED [ 66%]
tests/unit/test_streaming_consumer.py::test_watermark_and_lateness_evaluation_policy PASSED [ 67%]
tests/unit/test_streaming_consumer.py::test_deduplication_horizon_contract PASSED [ 69%]
tests/unit/test_streaming_consumer.py::test_consumer_configuration_validation PASSED [ 70%]
tests/unit/test_streaming_contract.py::test_valid_event_passes_validation PASSED [ 71%]
tests/unit/test_streaming_contract.py::test_valid_json_string_and_bytes_deserialization PASSED [ 73%]
tests/unit/test_streaming_contract.py::test_reject_malformed_json PASSED [ 74%]
tests/unit/test_streaming_contract.py::test_reject_unsupported_schema_version PASSED [ 75%]
tests/unit/test_streaming_contract.py::test_reject_missing_or_invalid_event_id PASSED [ 76%]
tests/unit/test_streaming_contract.py::test_reject_missing_trip_id PASSED [ 78%]
tests/unit/test_streaming_contract.py::test_reject_invalid_or_non_utc_timestamp PASSED [ 79%]
tests/unit/test_streaming_contract.py::test_reject_out_of_bounds_timestamp PASSED [ 80%]
tests/unit/test_streaming_contract.py::test_reject_invalid_h3_cell PASSED [ 82%]
tests/unit/test_streaming_contract.py::test_reject_coordinates_out_of_bounds PASSED [ 83%]
tests/unit/test_streaming_contract.py::test_parquet_row_to_event_conversion PASSED [ 84%]
tests/unit/test_streaming_producer.py::test_producer_mock_publishing_and_accounting PASSED [ 85%]
tests/unit/test_streaming_producer.py::test_producer_with_offset_and_limit PASSED [ 87%]
tests/unit/test_streaming_producer.py::test_producer_delivery_failure_accounting PASSED [ 88%]
tests/unit/test_zone_universe.py::test_zone_universe_schema_definition PASSED [ 89%]
tests/unit/test_zone_universe.py::test_deterministic_zone_inclusion_and_threshold_boundary PASSED [ 91%]
tests/unit/test_zone_universe.py::test_production_evidence_invariance_during_testing PASSED [ 92%]
tests/unit/test_zone_universe.py::test_full_dataset_reconciliation_and_properties PASSED [ 93%]
tests/unit/test_zone_universe.py::test_provisional_rule_and_metadata PASSED [ 94%]
tests/unit/test_zone_universe.py::test_catalog_completeness_all_239_cells_preserved PASSED [ 96%]
tests/unit/test_zone_universe.py::test_temporal_leakage_sensitivity_cdt_aligned PASSED [ 97%]
tests/unit/test_zone_universe.py::test_half_open_interval_and_split_durations PASSED [ 98%]
tests/unit/test_zone_universe.py::test_is_operational_universe_is_retrospective_full_month PASSED [100%]

======================= 76 passed, 2 skipped in 24.82s ========================
```

---

## 10. Phase 1 Artifact Hash Invariance

All 10 Phase 1 production datasets and reports were audited against their canonical SHA-256 hashes:

| File Path | Canonical SHA-256 Hash | Audited SHA-256 Hash | Status |
| :--- | :--- | :--- | :---: |
| `data/raw/chicago_taxi_trips_2022-06.jsonl` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | **MATCH** |
| `docs/evidence/clean_run_summary.json` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | **MATCH** |
| `reports/ingest_exclusion_audit.json` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | **MATCH** |
| `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | **MATCH** |
| `data/interim/excluded_trips_2022-06/excluded_trips.parquet` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | **MATCH** |
| `docs/evidence/h3_resolution_comparison.json` | `55EA02583ED890D4C023990E090BFAB54FE04885A291D4E1EB5EEE1C55295A49` | `55EA02583ED890D4C023990E090BFAB54FE04885A291D4E1EB5EEE1C55295A49` | **MATCH** |
| `docs/evidence/h3_resolution_comparison.md` | `E9B206B5AA266E20287A24DA677F51654E03910984BA277C6BC9E40E7E9A0806` | `E9B206B5AA266E20287A24DA677F51654E03910984BA277C6BC9E40E7E9A0806` | **MATCH** |
| `data/processed/zone_universe/zone_universe.parquet` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | **MATCH** |
| `docs/evidence/zone_universe_analysis.json` | `45D6EBB14EE5D9DEDB1F76688CEE5B6AFE4AA3C40C75C6DE345D8C6B2A03A9A5` | `45D6EBB14EE5D9DEDB1F76688CEE5B6AFE4AA3C40C75C6DE345D8C6B2A03A9A5` | **MATCH** |
| `docs/evidence/zone_universe_specification.md` | `F3F374D8F8891B6C7343B87551ABE060D15D5CBCD6983D4AF4A9E202B6F3186A` | `F3F374D8F8891B6C7343B87551ABE060D15D5CBCD6983D4AF4A9E202B6F3186A` | **MATCH** |

---

## 11. Known Limitations & Scope Boundaries

1. **Host Kafka Integration Status:** As established in Phase 2, live Kafka broker integration remains **BLOCKED** on this Windows host due to missing Docker/WSL2. The forecasting pipeline in Phase 3 operates directly on the immutable cleaned historical Parquet data.
2. **Peripheral Zone Sparsity:** Low-density zones exhibit severe zero-inflation, resulting in elevated WAPE figures even when MAE is under 0.2 trips. Downstream Phase 4 surge detection should focus primarily on High- and Medium-Density zones.
3. **No Premature Phase 4 Work:** No vehicle simulations, supply ratios, demand-supply pressure calculations ($C = V \times r$), or frontend code were introduced in this phase.

---

## 12. Recommendation for Phase 4 Progression

**Recommendation:** **READY FOR PHASE 4**.

The demand forecasting subsystem is mathematically sound, reproducible, strictly chronological, and delivers verified improvements over both baselines. All generated Parquet tables strictly follow `contracts/parquet_schemas.md` and are ready for consumption by Phase 4 simulation and supply monitoring.

