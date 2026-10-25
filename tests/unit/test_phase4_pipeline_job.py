"""
Integration unit tests for Phase 4 pipeline outputs and schema conformance.
"""

import os
import json
import pytest
import numpy as np
import pyarrow.parquet as pq


def test_phase4_artifacts_exist_and_conform():
    pressure_path = os.path.join("data", "processed", "simulation", "zone_pressure_status.parquet")
    surge_path = os.path.join("data", "processed", "simulation", "surge_alerts.parquet")
    summary_path = os.path.join("docs", "evidence", "phase4_supply_pressure_summary.json")

    assert os.path.exists(pressure_path), f"Missing {pressure_path}"
    assert os.path.exists(surge_path), f"Missing {surge_path}"
    assert os.path.exists(summary_path), f"Missing {summary_path}"

    # 1. Verify zone_pressure_status.parquet
    t_press = pq.read_table(pressure_path)
    assert t_press.num_rows == 116505
    cols = set(t_press.column_names)

    # Required by contracts/parquet_schemas.md Table 6
    expected_table6_cols = {
        "h3_cell", "as_of", "predicted_rides_D", "available_vehicles_V",
        "capacity_rate_r", "estimated_capacity_C", "pressure_index",
        "pressure_status", "input_status"
    }
    assert expected_table6_cols.issubset(cols), f"Missing Table 6 cols: {expected_table6_cols - cols}"

    # Required by Phase 4 prompt specifications
    expected_prompt_cols = {
        "forecast_demand_rides_30m", "simulated_available_vehicles",
        "estimated_supply_capacity_rides_30m", "demand_supply_ratio",
        "estimated_unserved_demand_rides", "pressure_level",
        "is_potential_surge", "supply_data_status"
    }
    assert expected_prompt_cols.issubset(cols), f"Missing prompt cols: {expected_prompt_cols - cols}"

    df_press = t_press.to_pandas()

    # 2. Assert NO INFINITY in numeric ratios
    ratios = df_press["pressure_index"].dropna().values
    assert not np.isinf(ratios).any(), "Found infinity in pressure_index!"

    # 3. Assert unserved demand is non-negative
    unserved = df_press["estimated_unserved_demand_rides"].dropna().values
    assert (unserved >= 0.0).all(), "Found negative unserved demand!"

    # 4. Assert supply labelling
    assert (df_press["supply_data_status"] == "SIMULATED_ESTIMATE").all()

    # 5. Assert unique zones count
    assert df_press["h3_cell"].nunique() == 135

    # 6. Verify surge_alerts.parquet (Table 7)
    t_surge = pq.read_table(surge_path)
    expected_table7_cols = {
        "alert_id", "h3_cell", "detected_at", "observed_demand", "severity", "simulation_run_id"
    }
    assert expected_table7_cols.issubset(set(t_surge.column_names))

    # 7. Verify JSON summary matches
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["coverage"]["total_records"] == 116505
    assert summary["coverage"]["unique_zones"] == 135
    assert summary["coverage"]["unique_origins"] == 863

