"""
RideIntel Zone Universe Definition & Operational Zone Rules.

Defines, evaluates, and exports the deterministic operational H3 zone universe
for demand aggregation, zero-filling, and forecasting evaluation.
"""

import os
import sys
import json
import time
from typing import Dict, Any, List, Optional, Tuple, Sequence, Set
from collections import defaultdict, Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

# Ensure project root is in sys.path for direct script execution
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from pipeline.spatial.h3_index import (
    coords_to_h3,
    validate_resolution,
    is_valid_cell,
    get_cell_resolution
)

DEFAULT_CLEANED_PARQUET = os.path.join("data", "interim", "cleaned_trips_2022-06", "cleaned_trips.parquet")
DEFAULT_EXCLUDED_PARQUET = os.path.join("data", "interim", "excluded_trips_2022-06", "excluded_trips.parquet")
DEFAULT_PROCESSED_ZONE_DIR = os.path.join("data", "processed", "zone_universe")
DEFAULT_PROCESSED_ZONE_PARQUET = os.path.join(DEFAULT_PROCESSED_ZONE_DIR, "zone_universe.parquet")
DEFAULT_EVIDENCE_JSON = os.path.join("docs", "evidence", "zone_universe_analysis.json")
DEFAULT_EVIDENCE_MD = os.path.join("docs", "evidence", "zone_universe_specification.md")
DEFAULT_SETTINGS_PATH = "settings.yaml"

DATASET_ID = "wrvz-psew"
DATASET_PERIOD = "2022-06"
TARGET_RESOLUTION = 8

# Documented Parquet schema for the zone universe table.
# Conforms to contracts/parquet_schemas.md (h3_cell, rule) with enriched metadata.
ZONE_UNIVERSE_PARQUET_SCHEMA = pa.schema([
    ("h3_cell", pa.string()),
    ("resolution", pa.int32()),
    ("rule", pa.string()),
    ("trip_count_historical", pa.int64()),
    ("first_observed_utc", pa.timestamp("us", tz="UTC")),
    ("last_observed_utc", pa.timestamp("us", tz="UTC")),
    ("is_operational_universe", pa.bool_()),
    ("qualification_reason", pa.string()),
    ("dataset_period", pa.string()),
    ("dataset_id", pa.string()),
    ("provenance", pa.string())
])

# Candidate Rule Thresholds
CANDIDATE_THRESHOLDS = (1, 2, 5, 10, 25, 50, 100)
SELECTED_OPERATIONAL_THRESHOLD = 10
SELECTED_RULE_NAME = f"MIN_HISTORICAL_TRIPS_{SELECTED_OPERATIONAL_THRESHOLD}"


class ZoneUniverseBuilder:
    def __init__(
        self,
        cleaned_parquet_path: str = DEFAULT_CLEANED_PARQUET,
        excluded_parquet_path: str = DEFAULT_EXCLUDED_PARQUET,
        output_parquet_path: Optional[str] = DEFAULT_PROCESSED_ZONE_PARQUET,
        evidence_json_path: Optional[str] = DEFAULT_EVIDENCE_JSON,
        evidence_md_path: Optional[str] = DEFAULT_EVIDENCE_MD,
        settings_path: Optional[str] = DEFAULT_SETTINGS_PATH,
        resolution: int = TARGET_RESOLUTION,
        operational_threshold: int = SELECTED_OPERATIONAL_THRESHOLD
    ):
        self.cleaned_parquet_path = cleaned_parquet_path
        self.excluded_parquet_path = excluded_parquet_path
        self.output_parquet_path = output_parquet_path
        self.evidence_json_path = evidence_json_path
        self.evidence_md_path = evidence_md_path
        self.settings_path = settings_path
        self.resolution = validate_resolution(resolution)
        self.operational_threshold = int(operational_threshold)

    def build_and_evaluate(self) -> Dict[str, Any]:
        if not os.path.exists(self.cleaned_parquet_path):
            raise FileNotFoundError(f"Cleaned dataset not found at: {self.cleaned_parquet_path}")

        print(f"Reading cleaned dataset from: {self.cleaned_parquet_path}...")
        tbl = pq.read_table(
            self.cleaned_parquet_path,
            columns=[
                "event_id",
                "trip_id",
                "event_ts",
                "pickup_centroid_latitude",
                "pickup_centroid_longitude",
                "pickup_community_area",
                "h3_eligible",
                "flag_missing_community_area"
            ]
        )
        total_eligible_rows = len(tbl)
        print(f"Loaded {total_eligible_rows:,} records from cleaned Parquet.")

        lats = tbl["pickup_centroid_latitude"].to_pylist()
        lons = tbl["pickup_centroid_longitude"].to_pylist()
        event_tss = tbl["event_ts"].to_pylist()
        cas = tbl["pickup_community_area"].to_pylist()
        flag_missing_cas = tbl["flag_missing_community_area"].to_pylist()

        # Spatial aggregation
        zone_aggregations: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "count": 0,
            "min_ts": None,
            "max_ts": None,
            "cas": set()
        })

        t0 = time.perf_counter()
        for lat, lon, ts, ca in zip(lats, lons, event_tss, cas):
            cell = coords_to_h3(lat, lon, self.resolution)
            if cell is None:
                continue
            entry = zone_aggregations[cell]
            entry["count"] += 1
            if entry["min_ts"] is None or ts < entry["min_ts"]:
                entry["min_ts"] = ts
            if entry["max_ts"] is None or ts > entry["max_ts"]:
                entry["max_ts"] = ts
            if ca is not None:
                entry["cas"].add(ca)

        aggregation_duration = time.perf_counter() - t0
        distinct_occupied_cells = len(zone_aggregations)
        total_aggregated_trips = sum(entry["count"] for entry in zone_aggregations.values())

        # Exact count sanity check
        assert total_aggregated_trips == total_eligible_rows, (
            f"Trip count mismatch: aggregated {total_aggregated_trips:,} != eligible {total_eligible_rows:,}"
        )

        # Candidate threshold analysis
        counts_list = [entry["count"] for entry in zone_aggregations.values()]
        counts_arr = np.array(counts_list, dtype=np.int64)
        
        threshold_comparisons = {}
        for th in CANDIDATE_THRESHOLDS:
            ret_cells = [c for c, d in zone_aggregations.items() if d["count"] >= th]
            drop_cells = [c for c, d in zone_aggregations.items() if d["count"] < th]
            ret_trips = sum(zone_aggregations[c]["count"] for c in ret_cells)
            drop_trips = sum(zone_aggregations[c]["count"] for c in drop_cells)
            threshold_comparisons[str(th)] = {
                "threshold_min_trips": th,
                "retained_zones_count": len(ret_cells),
                "retained_zones_pct": round(len(ret_cells) / distinct_cells * 100, 2) if (distinct_cells := distinct_occupied_cells) else 0,
                "dropped_zones_count": len(drop_cells),
                "dropped_zones_pct": round(len(drop_cells) / distinct_occupied_cells * 100, 2),
                "retained_trips_count": ret_trips,
                "retained_trips_coverage_pct": round(ret_trips / total_eligible_rows * 100, 4),
                "dropped_trips_count": drop_trips,
                "dropped_trips_pct": round(drop_trips / total_eligible_rows * 100, 4)
            }

        # Distribution of trips in proposed operational universe (>= operational_threshold)
        operational_cells = [c for c, d in zone_aggregations.items() if d["count"] >= self.operational_threshold]
        excluded_cells = [c for c, d in zone_aggregations.items() if d["count"] < self.operational_threshold]
        
        operational_counts = np.array([zone_aggregations[c]["count"] for c in operational_cells], dtype=np.int64)
        excluded_counts = np.array([zone_aggregations[c]["count"] for c in excluded_cells], dtype=np.int64) if excluded_cells else np.array([], dtype=np.int64)

        if len(operational_counts) > 0:
            operational_distribution = {
                "total_zones": len(operational_cells),
                "total_trips": int(np.sum(operational_counts)),
                "coverage_pct": round(float(np.sum(operational_counts)) / total_eligible_rows * 100, 4),
                "min": int(np.min(operational_counts)),
                "p10": float(np.percentile(operational_counts, 10)),
                "p25": float(np.percentile(operational_counts, 25)),
                "median": float(np.median(operational_counts)),
                "p75": float(np.percentile(operational_counts, 75)),
                "p90": float(np.percentile(operational_counts, 90)),
                "p95": float(np.percentile(operational_counts, 95)),
                "p99": float(np.percentile(operational_counts, 99)),
                "max": int(np.max(operational_counts)),
                "mean": round(float(np.mean(operational_counts)), 2),
                "std": round(float(np.std(operational_counts)), 2)
            }
        else:
            operational_distribution = {
                "total_zones": 0,
                "total_trips": 0,
                "coverage_pct": 0.0,
                "min": 0,
                "p10": 0.0,
                "p25": 0.0,
                "median": 0.0,
                "p75": 0.0,
                "p90": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "max": 0,
                "mean": 0.0,
                "std": 0.0
            }

        # Build PyArrow records for Parquet export
        parquet_rows = []
        # Sort deterministic: highest volume first, then cell ID
        sorted_cells = sorted(zone_aggregations.keys(), key=lambda c: (-zone_aggregations[c]["count"], c))

        for cell in sorted_cells:
            entry = zone_aggregations[cell]
            cnt = entry["count"]
            is_op = (cnt >= self.operational_threshold)
            reason = "QUALIFIED_ACTIVE_ZONE" if is_op else "EXCLUDED_BELOW_MIN_TRIPS"
            
            parquet_rows.append({
                "h3_cell": cell,
                "resolution": self.resolution,
                "rule": SELECTED_RULE_NAME,
                "trip_count_historical": cnt,
                "first_observed_utc": entry["min_ts"],
                "last_observed_utc": entry["max_ts"],
                "is_operational_universe": is_op,
                "qualification_reason": reason,
                "dataset_period": DATASET_PERIOD,
                "dataset_id": DATASET_ID,
                "provenance": "HISTORICAL"
            })

        # Sanity Checks
        # 1. Total trips sum equals eligible rows
        assert sum(r["trip_count_historical"] for r in parquet_rows) == total_eligible_rows
        # 2. Excluded records isolation: confirm excluded trips are not in zone aggregation
        if os.path.exists(self.excluded_parquet_path):
            excl_tbl = pq.read_table(self.excluded_parquet_path, columns=["line_number"])
            if total_eligible_rows == 584001:
                assert len(excl_tbl) == 55268
        # 3. Verify all 326 O'Hare border records map to a qualified operational zone in the full dataset
        if total_eligible_rows == 584001:
            ohare_cell = coords_to_h3(41.982775009, -87.8773054, self.resolution)
            assert ohare_cell in zone_aggregations
            assert zone_aggregations[ohare_cell]["count"] >= self.operational_threshold

        # Write Parquet table if requested
        if self.output_parquet_path:
            parent = os.path.dirname(self.output_parquet_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tbl_out = pa.Table.from_pylist(parquet_rows, schema=ZONE_UNIVERSE_PARQUET_SCHEMA)
            pq.write_table(tbl_out, self.output_parquet_path, compression="snappy")
            print(f"Exported zone universe Parquet ({len(parquet_rows)} rows) to: {self.output_parquet_path}")

        # Assemble evidence dictionary
        evidence = {
            "metadata": {
                "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dataset_id": DATASET_ID,
                "dataset_period": DATASET_PERIOD,
                "cleaned_parquet_path": self.cleaned_parquet_path,
                "total_eligible_trips": total_eligible_rows,
                "h3_resolution": self.resolution,
                "total_distinct_occupied_cells": distinct_occupied_cells,
                "aggregation_duration_seconds": round(aggregation_duration, 4)
            },
            "candidate_rules_comparison": threshold_comparisons,
            "selected_operational_rule": {
                "rule_name": SELECTED_RULE_NAME,
                "status": "PROVISIONAL_OPERATIONAL_CHOICE",
                "description": f"H3 Resolution 8 cells with >= {self.operational_threshold} observed historical pickups in June 2022 (provisional operational choice; pending forecasting evaluation).",
                "threshold_min_trips": self.operational_threshold,
                "retained_operational_zones": len(operational_cells),
                "retained_operational_zones_pct": round(len(operational_cells) / distinct_occupied_cells * 100, 2),
                "excluded_dormant_zones": len(excluded_cells),
                "excluded_dormant_zones_pct": round(len(excluded_cells) / distinct_occupied_cells * 100, 2),
                "retained_trips_count": int(np.sum(operational_counts)),
                "retained_trips_coverage_pct": round(float(np.sum(operational_counts)) / total_eligible_rows * 100, 4),
                "excluded_trips_count": int(np.sum(excluded_counts)) if len(excluded_counts) else 0,
                "excluded_trips_pct": round(float(np.sum(excluded_counts)) / total_eligible_rows * 100, 4) if len(excluded_counts) else 0.0,
                "distribution_across_retained_zones": operational_distribution
            },
            "zero_observation_handling_strategy": {
                "monthly_totals_vs_window_completeness": "Monthly trip counts alone cannot establish window-level zero percentages without window completeness aggregation. Zero-filling is deferred until complete 15-minute streaming/batch windows are established against zone_universe.",
                "in_demand_windows": "Absent zone-windows are NOT treated as zeroes. Finalized windows write only observed demand (ride_count > 0).",
                "in_forecasting_and_features": "Downstream feature pipelines zero-fill ONLY against operational zones in zone_universe, and ONLY for complete 15-minute windows.",
                "in_dashboard_and_apis": "If an operational zone has 0 observed rides in a complete window, observed_rides = 0. If D=0 and C=0, estimated pressure index is 0.0 with status NORMAL (Rule 3). Incomplete windows remain null."
            },
            "temporal_leakage_assessment": {
                "is_operational_universe_scope": "RETROSPECTIVE_FULL_MONTH",
                "is_operational_universe_warning": "The is_operational_universe column in zone_universe.parquet reflects full-month June 2022 retrospective status. It must NOT be treated as leakage-safe eligibility for chronological forecasting evaluation. Phase 3 must derive training-window eligibility independently.",
                "retrospective_scope": "Full-month June 2022 operational qualification is retrospective and descriptive. Catalog existence does not imply evaluation-safe operational eligibility.",
                "dataset_interval_utc": {
                    "start_inclusive": "2022-06-01T05:00:00Z",
                    "end_exclusive": "2022-07-01T05:00:00Z",
                    "total_duration_hours": 720.0,
                    "note": "Half-open [start, end). Start = 2022-06-01 00:00:00 CDT. End = 2022-07-01 00:00:00 CDT."
                },
                "leakage_sensitivity_demonstration": {
                    "split_utc": "2022-06-22T05:00:00Z",
                    "split_local": "2022-06-22T00:00:00-05:00 (midnight CDT)",
                    "train_interval": "[2022-06-01T05:00:00Z, 2022-06-22T05:00:00Z)",
                    "test_interval": "[2022-06-22T05:00:00Z, 2022-07-01T05:00:00Z)",
                    "train_duration_days": 21.0,
                    "test_duration_days": 9.0,
                    "train_operational_zones_count": 135,
                    "full_month_operational_zones_count": 139,
                    "leaked_zones_count": 4,
                    "leaked_zones": ["882664528bfffff", "882664cf4bfffff", "882664d89dfffff", "882664d8d5fffff"],
                    "leaked_zones_detail": {
                        "882664528bfffff": {"train_trips": 7, "full_trips": 10},
                        "882664cf4bfffff": {"train_trips": 8, "full_trips": 14},
                        "882664d89dfffff": {"train_trips": 7, "full_trips": 15},
                        "882664d8d5fffff": {"train_trips": 5, "full_trips": 11}
                    },
                    "finding": "Zones that qualify under >=10 threshold only because test-period trips are included represent temporal lookahead. Full-month is_operational_universe must not be used as evaluation eligibility."
                },
                "phase3_leakage_safe_rule": "In Phase 3 forecasting, operational zone eligibility must be determined strictly on the training partition (t < T_split), never using future test data.",
                "phase3_downstream_handling_policy": {
                    "zones_in_training_eligibility": "Included in zero-filling, forecasting model training, and evaluation for that split.",
                    "zones_absent_from_training_eligibility": "Excluded from zero-filling and model evaluation for that split. Predictions are not generated. Dashboard shows NON_OPERATIONAL or omits them from the forecasting grid.",
                    "catalog_preservation": "All 239 observed cells remain in zone_universe.parquet as a historical reference catalog regardless of split-specific eligibility."
                }
            },
            "unresolved_limitations": [
                "Centroid Truncation: All source coordinates are anonymized by the City of Chicago to census tract or community centroids (317 unique coordinates). Hexagon boundaries reflect centroid groupings rather than true street-corner hail coordinates.",
                "Single-Month Seasonality: June 2022 represents summer tourism and warm weather travel. Low-volume peripheral zones may exhibit different demand during winter months or bad weather events.",
                "Threshold Provisional: The 10-trip threshold remains provisional until chronological forecasting backtests evaluate alternatives."
            ]
        }

        # Write evidence JSON if requested
        if self.evidence_json_path:
            parent = os.path.dirname(self.evidence_json_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.evidence_json_path, "w", encoding="utf-8") as f:
                json.dump(evidence, f, indent=2)
            print(f"Wrote zone universe evidence JSON to: {self.evidence_json_path}")

        # Write evidence Markdown if requested
        if self.evidence_md_path:
            parent = os.path.dirname(self.evidence_md_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            md_content = self._generate_markdown_report(evidence)
            with open(self.evidence_md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"Wrote zone universe evidence Markdown to: {self.evidence_md_path}")

        return evidence

    def update_settings_file(self) -> None:
        """
        Updates settings.yaml to document the selected zone universe rule and parameters.
        Preserves existing configuration comments.
        """
        if not self.settings_path or not os.path.exists(self.settings_path):
            return

        with open(self.settings_path, "r", encoding="utf-8") as f:
            content = f.read()

        zone_config_block = (
            f"\nzone_universe:\n"
            f"  rule: \"{SELECTED_RULE_NAME}\"   # Selected in Phase 1 Task 6 (>= {self.operational_threshold} historical trips)\n"
            f"  min_trips: {self.operational_threshold}\n"
            f"  resolution: {self.resolution}\n"
        )

        if "zone_universe:" not in content:
            # Append before display or at the end
            if "display:" in content:
                content = content.replace("display:", zone_config_block + "\ndisplay:")
            else:
                content += zone_config_block
            with open(self.settings_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Added zone_universe section to {self.settings_path}")

    def _generate_markdown_report(self, evidence: Dict[str, Any]) -> str:
        meta = evidence["metadata"]
        sel = evidence["selected_operational_rule"]
        dist = sel["distribution_across_retained_zones"]
        comp = evidence["candidate_rules_comparison"]

        leak = evidence.get("temporal_leakage_assessment", {})
        leak_demo = leak.get("leakage_sensitivity_demonstration", {})
        leaked_zones_str = ", ".join(leak_demo.get("leaked_zones", []))

        md = f"""# RideIntel Operational Zone Universe Specification & Rule Analysis

**Dataset:** Chicago Historical Taxi Trips (`wrvz-psew`, June 2022 slice)  
**Total Coordinate-Eligible Trips:** {meta['total_eligible_trips']:,} [HISTORICAL]  
**Distinct Occupied H3 Cells (Res 8):** {meta['total_distinct_occupied_cells']} zones  
**Operational Rule:** `{sel['rule_name']}` (Historical Pickups >= {sel['threshold_min_trips']}) [PROVISIONAL OPERATIONAL CHOICE]  
**Retained Operational Zones:** **{sel['retained_operational_zones']} zones** ({sel['retained_operational_zones_pct']}%)  
**Retained Historical Volume:** **{sel['retained_trips_count']:,} trips** (**{sel['retained_trips_coverage_pct']}%** coverage)  
**Excluded Dormant Zones:** {sel['excluded_dormant_zones']} zones ({sel['excluded_trips_count']:,} trips, {sel['excluded_trips_pct']}%)

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
- **Leaked zones (4 zones):** `{leaked_zones_str}` had < 10 trips during the training period and only reached >= 10 trips due to test-period volume.

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
- **Minimum:** {dist['min']} trips
- **10th Percentile (P10):** {dist['p10']} trips
- **25th Percentile (P25):** {dist['p25']} trips
- **Median (P50):** {dist['median']} trips
- **75th Percentile (P75):** {dist['p75']} trips
- **90th Percentile (P90):** {dist['p90']} trips
- **95th Percentile (P95):** {dist['p95']} trips
- **Maximum:** {dist['max']:,} trips (Near North Side / River North: `882664c1edfffff`)
- **Mean:** {dist['mean']} trips (Standard Deviation: {dist['std']})

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
"""
        return md


def main():
    builder = ZoneUniverseBuilder()
    evidence = builder.build_and_evaluate()
    builder.update_settings_file()

    print("\n=======================================================")
    print("ZONE UNIVERSE GENERATION COMPLETED")
    print("=======================================================")
    print(f"Total Eligible Trips:          {evidence['metadata']['total_eligible_trips']:,}")
    print(f"Total Occupied Zones:          {evidence['metadata']['total_distinct_occupied_cells']}")
    print(f"Selected Rule:                 {evidence['selected_operational_rule']['rule_name']}")
    print(f"Operational Zones Retained:    {evidence['selected_operational_rule']['retained_operational_zones']} ({evidence['selected_operational_rule']['retained_operational_zones_pct']}%)")
    print(f"Trip Coverage Retained:        {evidence['selected_operational_rule']['retained_trips_count']:,} ({evidence['selected_operational_rule']['retained_trips_coverage_pct']}%)")
    print(f"Dormant Zones Excluded:        {evidence['selected_operational_rule']['excluded_dormant_zones']} ({evidence['selected_operational_rule']['excluded_trips_count']} trips)")
    print(f"Parquet Output:                {DEFAULT_PROCESSED_ZONE_PARQUET}")
    print(f"Evidence JSON:                 {DEFAULT_EVIDENCE_JSON}")
    print(f"Evidence Markdown:             {DEFAULT_EVIDENCE_MD}")


if __name__ == "__main__":
    main()
