"""
Unit tests for demand-supply pressure and surge detection modules.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from pipeline.simulation.pressure import (
    evaluate_single_pressure_record,
    compute_demand_supply_pressure_table
)
from pipeline.simulation.surge import (
    evaluate_surge_for_row,
    detect_potential_surges
)
from pipeline.simulation import (
    STATUS_NORMAL,
    STATUS_ELEVATED,
    STATUS_HIGH_PRESSURE,
    STATUS_NO_CAPACITY,
    STATUS_UNKNOWN,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_HIGH,
    LEVEL_CRITICAL,
    LEVEL_NO_CAPACITY,
    LEVEL_UNKNOWN,
    INPUT_STATUS_OK,
    INPUT_STATUS_MISSING
)


def test_pressure_rule_1_missing_or_stale():
    # Missing demand
    r1 = evaluate_single_pressure_record(demand_d=None, vehicles_v=10, capacity_rate_r=2.0)
    assert r1["pressure_status"] == STATUS_UNKNOWN
    assert r1["pressure_level"] == LEVEL_UNKNOWN
    assert r1["pressure_index"] is None

    # Missing vehicles
    r2 = evaluate_single_pressure_record(demand_d=15.0, vehicles_v=None, capacity_rate_r=2.0)
    assert r2["pressure_status"] == STATUS_UNKNOWN
    assert r2["pressure_index"] is None


def test_pressure_rule_2_zero_capacity_positive_demand():
    """
    CRITICAL CONTRACT RULE (contracts/parquet_schemas.md):
    C = 0 and D > 0 -> NO_ESTIMATED_CAPACITY, index null.
    NEVER serialize infinity!
    """
    res = evaluate_single_pressure_record(demand_d=12.0, vehicles_v=0, capacity_rate_r=2.0)
    assert res["pressure_status"] == STATUS_NO_CAPACITY
    assert res["pressure_level"] == LEVEL_NO_CAPACITY
    assert res["pressure_index"] is None
    assert res["demand_supply_ratio"] is None
    assert res["estimated_capacity_C"] == 0.0
    assert res["estimated_unserved_demand_rides"] == 12.0


def test_pressure_rule_3_zero_capacity_zero_demand():
    """
    CRITICAL CONTRACT RULE:
    C = 0 and D = 0 -> NORMAL, index 0.0.
    """
    res = evaluate_single_pressure_record(demand_d=0.0, vehicles_v=0, capacity_rate_r=2.0)
    assert res["pressure_status"] == STATUS_NORMAL
    assert res["pressure_level"] == LEVEL_LOW
    assert res["pressure_index"] == 0.0
    assert res["demand_supply_ratio"] == 0.0
    assert res["estimated_unserved_demand_rides"] == 0.0


def test_pressure_rule_4_positive_capacity_thresholds():
    # V = 10, r = 2.0 -> C = 20.0
    # Case A: D = 10.0 -> P = 0.5 (< 0.8 -> NORMAL / LOW)
    r_low = evaluate_single_pressure_record(demand_d=10.0, vehicles_v=10, capacity_rate_r=2.0)
    assert r_low["pressure_index"] == 0.5
    assert r_low["pressure_status"] == STATUS_NORMAL
    assert r_low["pressure_level"] == LEVEL_LOW
    assert r_low["estimated_unserved_demand_rides"] == 0.0

    # Case B: D = 17.0 -> P = 0.85 (0.8 <= P < 1.0 -> ELEVATED / MODERATE)
    r_mod = evaluate_single_pressure_record(demand_d=17.0, vehicles_v=10, capacity_rate_r=2.0)
    assert np.isclose(r_mod["pressure_index"], 0.85)
    assert r_mod["pressure_status"] == STATUS_ELEVATED
    assert r_mod["pressure_level"] == LEVEL_MODERATE
    assert r_mod["estimated_unserved_demand_rides"] == 0.0

    # Case C: D = 22.0 -> P = 1.1 (1.0 < P < 1.2 -> HIGH_PRESSURE / HIGH)
    r_high = evaluate_single_pressure_record(demand_d=22.0, vehicles_v=10, capacity_rate_r=2.0)
    assert np.isclose(r_high["pressure_index"], 1.1)
    assert r_high["pressure_status"] == STATUS_HIGH_PRESSURE
    assert r_high["pressure_level"] == LEVEL_HIGH
    assert r_high["estimated_unserved_demand_rides"] == 2.0  # 22 - 20 = 2

    # Case D: D = 30.0 -> P = 1.5 (P >= 1.2 -> HIGH_PRESSURE / CRITICAL)
    r_crit = evaluate_single_pressure_record(demand_d=30.0, vehicles_v=10, capacity_rate_r=2.0)
    assert np.isclose(r_crit["pressure_index"], 1.5)
    assert r_crit["pressure_status"] == STATUS_HIGH_PRESSURE
    assert r_crit["pressure_level"] == LEVEL_CRITICAL
    assert r_crit["estimated_unserved_demand_rides"] == 10.0  # 30 - 20 = 10


def test_surge_detection_heuristics():
    # 1. Low demand below min threshold (D = 3.0 < 5.0) -> NO surge
    s1 = evaluate_surge_for_row(forecast_demand=3.0, capacity=2.0, pressure_ratio=1.5)
    assert s1["is_potential_surge"] is False
    assert s1["surge_severity"] == "NONE"

    # 2. Zero capacity with D = 12.0 -> CRITICAL surge
    s2 = evaluate_surge_for_row(forecast_demand=12.0, capacity=0.0, pressure_ratio=None)
    assert s2["is_potential_surge"] is True
    assert s2["surge_severity"] == "CRITICAL"

    # 3. Ratio >= 1.2 with demand >= 5.0 and growth -> SURGE
    s3 = evaluate_surge_for_row(
        forecast_demand=20.0,
        capacity=10.0,
        pressure_ratio=2.0,
        baseline_demand=10.0
    )
    assert s3["is_potential_surge"] is True
    assert s3["surge_severity"] == "CRITICAL"

