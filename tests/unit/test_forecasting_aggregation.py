"""
Unit tests for forecasting aggregation, window completeness policy, and zone eligibility.
"""

import pytest
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from pipeline.forecasting.aggregation import (
    floor_to_window,
    generate_window_grid,
    is_window_complete,
    create_zero_filled_demand_grid,
    compute_target_demand
)
from pipeline.forecasting.eligibility import (
    derive_training_eligible_zones,
    identify_leaked_zones
)
from pipeline.forecasting import (
    DATASET_START_UTC,
    DATASET_END_UTC,
    TRAIN_TEST_SPLIT_UTC
)


def test_floor_to_window():
    # 05:07 -> 05:00
    t1 = datetime(2022, 6, 1, 5, 7, 23, tzinfo=timezone.utc)
    assert floor_to_window(t1, 15) == datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)

    # Exact boundary 05:15 -> 05:15
    t2 = datetime(2022, 6, 1, 5, 15, 0, tzinfo=timezone.utc)
    assert floor_to_window(t2, 15) == datetime(2022, 6, 1, 5, 15, 0, tzinfo=timezone.utc)

    # 05:29:59 -> 05:15
    t3 = datetime(2022, 6, 1, 5, 29, 59, tzinfo=timezone.utc)
    assert floor_to_window(t3, 15) == datetime(2022, 6, 1, 5, 15, 0, tzinfo=timezone.utc)


def test_window_grid_generation_full_month():
    grid = generate_window_grid(DATASET_START_UTC, DATASET_END_UTC, window_minutes=15)
    # Exactly 30 days * 24 hours * 4 windows = 2880 windows
    assert len(grid) == 2880
    assert grid[0] == DATASET_START_UTC
    assert grid[-1] == DATASET_END_UTC - timedelta(minutes=15)


def test_is_window_complete():
    # Interior window
    w_valid = datetime(2022, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert is_window_complete(w_valid) is True

    # First window
    assert is_window_complete(DATASET_START_UTC) is True

    # Last complete window in dataset
    last_valid = DATASET_END_UTC - timedelta(minutes=15)
    assert is_window_complete(last_valid) is True

    # Window starting at dataset end (spills past end)
    assert is_window_complete(DATASET_END_UTC) is False

    # Window before dataset start
    before_start = DATASET_START_UTC - timedelta(minutes=15)
    assert is_window_complete(before_start) is False


def test_zero_filling_policy_on_synthetic_data():
    start = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 1, 6, 0, 0, tzinfo=timezone.utc)  # 4 windows: 05:00, 05:15, 05:30, 05:45
    zones = ["zone_A", "zone_B"]

    # Observed only in 05:00 for zone_A (count=5), and 05:30 for zone_B (count=2)
    obs = pd.DataFrame([
        {"window_start": start, "h3_cell": "zone_A", "ride_count": 5},
        {"window_start": start + timedelta(minutes=30), "h3_cell": "zone_B", "ride_count": 2}
    ])

    grid = create_zero_filled_demand_grid(obs, zones, start_utc=start, end_utc=end, window_minutes=15)

    # 4 windows * 2 zones = 8 rows
    assert len(grid) == 8

    # Check observed preservation
    row_a0 = grid[(grid["window_start"] == start) & (grid["h3_cell"] == "zone_A")].iloc[0]
    assert row_a0["ride_count"] == 5
    assert row_a0["demand_status"] == "HISTORICAL_OBSERVED"

    # Check zero fill
    row_b0 = grid[(grid["window_start"] == start) & (grid["h3_cell"] == "zone_B")].iloc[0]
    assert row_b0["ride_count"] == 0
    assert row_b0["demand_status"] == "ZERO_FILLED_COMPLETE_WINDOW"


def test_compute_target_demand_calculation():
    start = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 1, 6, 0, 0, tzinfo=timezone.utc)  # 4 windows
    zones = ["zone_A"]

    grid = pd.DataFrame([
        {"window_start": start, "h3_cell": "zone_A", "ride_count": 3, "demand_status": "HISTORICAL_OBSERVED"},
        {"window_start": start + timedelta(minutes=15), "h3_cell": "zone_A", "ride_count": 4, "demand_status": "HISTORICAL_OBSERVED"},
        {"window_start": start + timedelta(minutes=30), "h3_cell": "zone_A", "ride_count": 2, "demand_status": "HISTORICAL_OBSERVED"},
        {"window_start": start + timedelta(minutes=45), "h3_cell": "zone_A", "ride_count": 1, "demand_status": "HISTORICAL_OBSERVED"},
    ])

    targets = compute_target_demand(grid, horizon_minutes=30, window_minutes=15)

    # 4 windows with horizon 30m (2 steps):
    # T0 (05:00): sum(W0, W1) = 3 + 4 = 7
    # T1 (05:15): sum(W1, W2) = 4 + 2 = 6
    # T2 (05:30): sum(W2, W3) = 2 + 1 = 3
    # T3 (05:45): cannot form full 30m window, excluded!
    assert len(targets) == 3

    t0 = targets[targets["origin"] == start].iloc[0]
    assert t0["target_rides_30m"] == 7
    assert t0["target_end"] == start + timedelta(minutes=30)

    t1 = targets[targets["origin"] == start + timedelta(minutes=15)].iloc[0]
    assert t1["target_rides_30m"] == 6

    t2 = targets[targets["origin"] == start + timedelta(minutes=30)].iloc[0]
    assert t2["target_rides_30m"] == 3


def test_training_eligibility_derivation_real_dataset():
    res = derive_training_eligible_zones()
    assert res["eligible_zone_count"] == 135
    assert res["total_train_trips"] == 413565
    assert len(res["zone_counts"]) == 216

    # Test leaked zones detection
    leaked = identify_leaked_zones(set(res["eligible_zones"]))
    assert len(leaked) == 4
    expected_leaked = ["882664528bfffff", "882664cf4bfffff", "882664d89dfffff", "882664d8d5fffff"]
    assert sorted(leaked) == sorted(expected_leaked)

