# RideIntel Phase 4 — Final Supply Simulation and Surge Logic Audit Report

**Audit Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand Analysis  
**Phase:** Phase 4 (Supply Simulation, Demand-Supply Pressure & Surge Detection)  
**Auditor:** Senior Data & ML Engineer  
**Audit Verdict:** **PASS WITH LIMITATIONS**  

---

## 1. Executive Summary & Audit Verdict

This document presents the final, independent audit of the RideIntel Phase 4 implementation. All output artifacts, mathematical formulas, boundary conditions, edge cases, simulation sensitivity, and contract invariants were audited against `contracts/parquet_schemas.md` (Table 6: `zone_status`, Table 7: `surge_alerts`), `AGENTS.md`, and `settings.yaml`.

### Verdict: **PASS WITH LIMITATIONS**
- **Artifact Reconciliations:** Exactly 116,505 zone-window pressure records across 863 prediction origins and 135 operational zones; zero duplicate pairs; exactly 8 surge alert records matching all trigger criteria.
- **Contract Conformance:** Evaluated strictly in the hierarchical rule order specified in Table 6. Pressure index $P = D / C$ is null when $C = 0$ or input is missing/stale. Never serializes infinity or NaN.
- **Zero-Capacity Frequency ($C = 0, D > 0$):** Exactly 39,183 records (33.63%), predominantly micro-demand ($< 0.5$ rides per 30 minutes) in peripheral zones. 0 records with $D \ge 5.0$ rides have zero capacity. No peripheral micro-demand record was falsely flagged as a surge alert.
- **Simulation Sensitivity:** Non-destructive sensitivity tests confirmed expected physical responses across fleet scales ($1,500 - 3,500$) and capacity rates ($r \in [1.5, 2.5]$).
- **Artifact Invariance:** All 10 canonical Phase 1 datasets and Phase 3 model/forecast artifacts remain byte-identical (verified via SHA-256 hashes).
- **Limitations:**
  1. *Simulated Supply Nature:* Vehicle inventory is simulated decision support, not measured GPS telemetry.
  2. *Live Broker Integration:* Kafka live broker integration remains marked `BLOCKED` due to host absence of Docker/WSL2.

---

## 2. Section A: Reconcile Output Counts & Metrics

Independent audit calculations directly against `data/processed/simulation/zone_pressure_status.parquet`, `data/processed/simulation/surge_alerts.parquet`, and `data/processed/forecasts/forecasts.parquet`:

| Metric | Required / Contract Value | Audited Value | Status |
| :--- | :--- | :--- | :---: |
| Total Zone-Window Pressure Records | 116,505 | 116,505 | **EXACT MATCH** |
| Unique Prediction Origins | 863 | 863 (`2022-06-22 05:00:00Z` to `2022-07-01 04:30:00Z`) | **EXACT MATCH** |
| Unique Operational H3 Zones | 135 | 135 | **EXACT MATCH** |
| Duplicate `(forecast_origin, h3_cell)` Pairs | 0 | 0 | **EXACT MATCH** |
| Forecast Target Duration | 30 minutes ($[T, T + 30\text{m})$) | Exactly 30.0 minutes | **EXACT MATCH** |
| Phase 3 XGBoost Alignment | 116,505 rows | 116,505 / 116,505 (100.0%) | **EXACT MATCH** |
| Total Saved Surge Alerts | 8 | 8 | **EXACT MATCH** |
| Total Estimated Unserved Demand | Calculated | 6,097.37 rides | **VERIFIED** |
| Negative Unserved Demand Count | 0 | 0 | **VERIFIED** |
| Ratio / Pressure Index Infinities | 0 (Strictly prohibited) | 0 | **VERIFIED** |
| Ratio Null Count | Exactly count where $C = 0$ | 39,183 | **VERIFIED** |

### Pressure Level & Status Distribution

```
--- Pressure Level Breakdown ---
  LOW            :  76,984 ( 66.08%)
  NO_CAPACITY    :  39,183 ( 33.63%)
  MODERATE       :     171 (  0.15%)
  CRITICAL       :      90 (  0.08%)
  HIGH           :      77 (  0.07%)
  Total          : 116,505 (100.00%)

--- Schema Table 6 Status Breakdown ---
  NORMAL                :  76,984 ( 66.08%)
  NO_ESTIMATED_CAPACITY :  39,183 ( 33.63%)
  ELEVATED              :     171 (  0.15%)
  HIGH_PRESSURE         :     167 (  0.14%)  [HIGH + CRITICAL]
  Total                 : 116,505 (100.00%)
```

### Complete Audit of the 8 Surge Alerts

Each saved alert was joined back to the forecast origin and pressure table to verify all conditions:

| Alert ID | Origin (UTC) | H3 Cell | Predicted Demand ($D$) | Estimated Capacity ($C$) | Ratio ($P$) | Pressure Level | Severity | Validated? |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `alert-6fbd6ffad23a` | 2022-06-22 14:45 | `882664cf21fffff` | 5.01 | 4.0 | 1.25 | CRITICAL | HIGH | **TRUE** |
| `alert-ce6d2948df5a` | 2022-06-23 16:45 | `882664cf21fffff` | 6.16 | 2.0 | 3.08 | CRITICAL | CRITICAL | **TRUE** |
| `alert-565ce69cb50f` | 2022-06-23 17:00 | `882664ca6bfffff` | 5.33 | 4.0 | 1.33 | CRITICAL | HIGH | **TRUE** |
| `alert-f16a4e674b54` | 2022-06-24 13:15 | `882664cac3fffff` | 6.43 | 4.0 | 1.61 | CRITICAL | CRITICAL | **TRUE** |
| `alert-c67c555fd469` | 2022-06-28 17:30 | `882664c117fffff` | 5.98 | 2.0 | 2.99 | CRITICAL | CRITICAL | **TRUE** |
| `alert-e081049af1b9` | 2022-06-29 19:45 | `882664cf21fffff` | 5.76 | 4.0 | 1.44 | CRITICAL | HIGH | **TRUE** |
| `alert-4ce6e844fadb` | 2022-06-30 17:45 | `882664d8e1fffff` | 5.01 | 4.0 | 1.25 | CRITICAL | HIGH | **TRUE** |
| `alert-75ce19214006` | 2022-06-30 21:45 | `882664c1e5fffff` | 9.79 | 8.0 | 1.22 | CRITICAL | HIGH | **TRUE** |

All 8 alerts satisfy:
1. $D \ge 5.0$ rides (`min_surge_demand: 5.0`).
2. $C > 0$ and $P \ge 1.20$ (`critical_ratio: 1.20`).
3. Pressure status is `HIGH_PRESSURE` with level `CRITICAL`.
4. None had $C = 0$.

---

## 3. Section B: Investigation of Zero-Capacity Frequency ($C = 0, D > 0$)

The implementation report documented that **39,183 records (33.63%)** have zero estimated capacity while having positive predicted demand ($C = 0, D > 0$). This audit conducted an exhaustive breakdown to establish whether this represents a defect or expected statistical behavior.

### Breakdown of $C = 0, D > 0$ by Forecast Demand Bands

| Demand Band | Ride Count Range | Number of Records | % of $C = 0$ Population | Cumulative % |
| :--- | :--- | :---: | :---: | :---: |
| **Micro Demand** | $D < 0.1$ rides | 22,537 | 57.52% | 57.52% |
| **Very Low Demand** | $0.1 \le D < 0.5$ rides | 14,388 | 36.72% | 94.24% |
| **Low Demand** | $0.5 \le D < 1.0$ rides | 1,786 | 4.56% | 98.80% |
| **Moderate Demand** | $1.0 \le D < 2.0$ rides | 428 | 1.09% | 99.89% |
| **Elevated Demand** | $2.0 \le D < 5.0$ rides | 44 | 0.11% | 100.00% |
| **High Demand** | $D \ge 5.0$ rides | **0** | **0.00%** | 100.00% |

- **Maximum Predicted Demand with $C = 0$:** Exactly **4.848 rides** (never exceeding the surge threshold of 5.0).
- **$D < 0.5$ rides:** Accounts for **94.24%** of all zero-capacity occurrences.

### Breakdown by Zone Historical Activity Quartiles

Correlating $C = 0$ occurrences with the historical trip activity of each zone:
- **Low/Medium-density zones (Quartiles 2 & 3):** Account for **94.66%** of all zero-capacity records (37,093 records).
- **High-density core zones (Quartile 4):** Account for only **5.33%** (2,090 records), occurring strictly during the deep night troughs (3 AM – 5 AM) when the citywide diurnal curve dips to 35% availability.

### Statistical Mechanism
1. **Multinomial Sparsity:** Under the multinomial allocation of 2,500 fleet vehicles scaled by diurnal factor $\alpha(T) \in [0.35, 0.90]$ across 135 zones, peripheral zones with prior probability $p_i \approx 0.0005 - 0.001$ frequently receive 0 vehicles ($P(V_i = 0) \approx (1 - p_i)^{N_{\text{avail}}} \approx 0.35 - 0.65$).
2. **Continuous ML Predictions:** XGBoost outputs continuous non-zero predictions (e.g., $D = 0.02, 0.08, 0.24$) even for peripheral zones where historical trips are rare.
3. **Protection against False Surges:** Because `min_surge_demand: 5.0`, none of the 39,183 zero-capacity peripheral records were mislabeled as a surge alert (`surge_trigger_reason: DEMAND_BELOW_MINIMUM_THRESHOLD`).
4. **Unserved Demand Conformance:** When $C = 0$, $\text{Unserved} = \max(0, D - 0) = D$. Across all 39,183 records, unserved demand exactly equals $D$, contributing 5,969.66 rides (97.91% of total unserved demand, averaging only $0.15$ rides per window).

---

## 4. Section C: Supply Simulation Sensitivity Analysis

Non-destructive sensitivity simulations were executed across varying fleet sizes, diurnal bounds, and capacity rates. Production artifacts were preserved unchanged.

### Sensitivity Comparison Table

| Scenario | Fleet Size ($N$) | Capacity Rate ($r$) | $C = 0$ Recs (%) | Elevated/High/Crit Records | Total Unserved Demand (rides) | Surge Alerts |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline (Configured)** | **2,500** | **2.0** | **33.63%** | **338** | **6,097.37** | **8** |
| **Low Fleet Scale** | 1,500 | 2.0 | 43.27% | 1,238 | 11,101.77 | 88 |
| **High Fleet Scale** | 3,500 | 2.0 | 27.36% | 131 | 4,210.85 | 3 |
| **Low Service Rate** | 2,500 | 1.5 | 33.63% | 926 | 6,438.79 | 18 |
| **High Service Rate** | 2,500 | 2.5 | 33.63% | 167 | 6,032.11 | 3 |

### Sensitivity Insights:
1. **Fleet Size Impact on $C = 0$:** Reducing fleet size from 2,500 to 1,500 increases $C = 0$ frequency by $+9.64\%$, while increasing fleet to 3,500 drops it to $27.36\%$. This confirms that $C = 0$ is governed by multinomial allocation sample size.
2. **Service Rate ($r$) Decoupling:** Modifying $r$ does not affect $C = 0$ occurrences because $V = 0 \implies C = 0 \times r = 0$, but significantly affects pressure ratios ($P = D / (V \times r)$), shifting elevated/high records from 167 ($r = 2.5$) to 926 ($r = 1.5$).
3. **Surge Alert Sensitivity:** Surge alerts scale inversely with available capacity (from 88 alerts under scarce fleet down to 3 under abundant fleet), verifying that the surge heuristic correctly isolates capacity-constrained demand spikes.
4. **Seed Reproducibility vs. Real-World Accuracy:**
   - *Determinism:* Given seed 42, the supply simulation is 100% reproducible across operating systems and runs.
   - *Epistemic Limitation:* Real-world driver supply is governed by behavioral dispatch algorithms, deadheading, and dynamic pricing, not multinomial draws. The simulation is a controlled scenario generator for testing pressure-monitoring pipelines, not an empirical fleet census.

---

## 5. Section D: Audit of Pressure and Surge Rules

Boundary conditions and edge cases were tested against `evaluate_single_pressure_record`:

### Boundary Tests ($P \in \{0.8, 1.0, 1.2\}$)

| Test Case | Demand ($D$) | Vehicles ($V$) | Rate ($r$) | Ratio ($P$) | Pressure Status | Pressure Level | Unserved Demand | Result |
| :--- | :---: | :---: | :---: | :---: | :--- | :--- | :---: | :---: |
| Ratio $0.799 < 0.80$ | 7.99 | 5 | 2.0 | 0.799 | `NORMAL` | `LOW` | 0.0 | **PASS** |
| Ratio $0.800 = 0.80$ | 8.00 | 5 | 2.0 | 0.800 | `ELEVATED` | `MODERATE` | 0.0 | **PASS** |
| Ratio $0.999 < 1.00$ | 9.99 | 5 | 2.0 | 0.999 | `ELEVATED` | `MODERATE` | 0.0 | **PASS** |
| Ratio $1.000 = 1.00$ | 10.00 | 5 | 2.0 | 1.000 | `ELEVATED` | `MODERATE` | 0.0 | **PASS** |
| Ratio $1.001 > 1.00$ | 10.01 | 5 | 2.0 | 1.001 | `HIGH_PRESSURE` | `HIGH` | 0.01 | **PASS** |
| Ratio $1.199 < 1.20$ | 11.99 | 5 | 2.0 | 1.199 | `HIGH_PRESSURE` | `HIGH` | 1.99 | **PASS** |
| Ratio $1.200 \ge 1.20$ | 12.00 | 5 | 2.0 | 1.200 | `HIGH_PRESSURE` | `CRITICAL` | 2.00 | **PASS** |

### Edge Case Tests

| Scenario | $D$ | $V$ | Input Status | Pressure Status | Pressure Level | Ratio ($P$) | Unserved | Prohibited Infs/NaNs? |
| :--- | :---: | :---: | :---: | :--- | :--- | :---: | :---: | :---: |
| $C = 0, D > 0$ | 2.5 | 0 | `OK` | `NO_ESTIMATED_CAPACITY` | `NO_CAPACITY` | `null` | 2.5 | None (No Infs) |
| $C = 0, D = 0$ | 0.0 | 0 | `OK` | `NORMAL` | `LOW` | 0.0 | 0.0 | None |
| $C > 0, D = 0$ | 0.0 | 5 | `OK` | `NORMAL` | `LOW` | 0.0 | 0.0 | None |
| Missing Forecast | `None` | 5 | `MISSING` | `UNKNOWN` | `UNKNOWN` | `null` | `null` | None |
| Stale Forecast | `None` | 5 | `STALE` | `UNKNOWN` | `UNKNOWN` | `null` | `null` | None |

---

## 6. Section E: Causality, Contract Conformance & Artifact Invariance

### Causality & Zero Lookahead Verification
- All simulated vehicle availability draws at prediction origin $T$ use strictly:
  1. Parametric diurnal curve evaluated at origin $T$ (America/Chicago local time).
  2. Spatial multinomial weights derived strictly from training data priors.
  3. No future test set actual trips, held-out test labels, or future predictions are accessed.

### Schema Conformance
- Output table `zone_pressure_status.parquet` conforms to `contracts/parquet_schemas.md` (Table 6).
- Output table `surge_alerts.parquet` conforms to `contracts/parquet_schemas.md` (Table 7).

### Canonical Hash Invariance Verification (Phases 1–3)

All canonical artifacts were hashed via SHA-256 and compared against established benchmarks:

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
| `data/processed/forecasts/forecasts.parquet` | `992A44F66F56F1E5579DDEFBE0EC445FF6D705D7E6B8F7EC9A50C1FF6180E7BD` | `992A44F66F56F1E5579DDEFBE0EC445FF6D705D7E6B8F7EC9A50C1FF6180E7BD` | **MATCH** |
| `data/processed/forecasts/forecast_evaluation.parquet` | `F7629ACD43404EBE551C492DDE682CA348891D69AF77558E8012F6D925954ACB` | `F7629ACD43404EBE551C492DDE682CA348891D69AF77558E8012F6D925954ACB` | **MATCH** |
| `models/xgboost_demand_model.json` | `D80607A641E07968D51AF3EB0D85F38966C18381A86BC16AD3615C44EF39FA74` | `D80607A641E07968D51AF3EB0D85F38966C18381A86BC16AD3615C44EF39FA74` | **MATCH** |

---

## 7. Section F: Complete Test Suite Execution & Output

The full project pytest test suite was executed across all units and integration test suites:

```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2
collected 87 items

tests\integration\test_streaming_pipeline.py ss                          [  2%]
tests\unit\test_clean_pipeline.py ......                                 [  9%]
tests\unit\test_cleaning_policy.py ........                              [ 18%]
tests\unit\test_forecasting_aggregation.py ......                        [ 25%]
tests\unit\test_forecasting_baselines.py ..                              [ 27%]
tests\unit\test_forecasting_evaluate.py ...                              [ 31%]
tests\unit\test_forecasting_features.py ...                              [ 34%]
tests\unit\test_forecasting_model.py ..                                  [ 36%]
tests\unit\test_forecasting_pipeline_job.py .                            [ 37%]
tests\unit\test_h3_comparison.py ....                                    [ 42%]
tests\unit\test_h3_index.py .......                                      [ 50%]
tests\unit\test_phase4_pipeline_job.py .                                 [ 51%]
tests\unit\test_pressure_and_surge.py .....                              [ 57%]
tests\unit\test_profile_raw.py ......                                    [ 64%]
tests\unit\test_streaming_consumer.py .....                              [ 70%]
tests\unit\test_streaming_contract.py ...........                        [ 82%]
tests\unit\test_streaming_producer.py ...                                [ 86%]
tests\unit\test_supply_simulation.py ...                                 [ 89%]
tests\unit\test_zone_universe.py .........                               [100%]

======================= 85 passed, 2 skipped in 33.46s ========================
```

- **Total Test Cases:** 87
- **Passing:** 85 (100% of unit and offline tests)
- **Skipped:** 2 (`tests\integration\test_streaming_pipeline.py` skipped due to missing live Kafka broker on host)
- **Failing / Errored:** 0

---

## 8. Summary of Findings & Next Steps

1. **Findings:**
   - The Phase 4 pipeline correctly aligns 30-minute demand forecasts with time-varying simulated supply across all 135 operational zones and 863 prediction origins.
   - The 33.63% frequency of zero capacity is mathematically explained by multinomial allocation across sparse peripheral zones and is protected against false-positive surge alerts by the minimum demand threshold.
   - The demand-supply pressure rules strictly conform to the hierarchy defined in `contracts/parquet_schemas.md` (Table 6).
   - Invariant hashes prove zero regression or corruption across Phases 1–3.

2. **Next Steps (Phase 5 Transition):**
   - No Phase 5 code (FastAPI REST service, Supabase sync, or React frontend) has been implemented.
   - Human review and approval of this audit report is requested before proceeding to Phase 5.

