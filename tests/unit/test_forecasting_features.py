"""
Unit tests for forecasting feature engineering and strict no-lookahead contract.
"""

import pytest
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from pipeline.forecasting.features import (
    extract_calendar_features,
    build_feature_table_for_origin,
    build_full_feature_matrix,
    FEATURE_COLUMNS
)
from pipeline.forecasting.aggregation import (
    generate_window_grid,
    create_zero_filled_demand_grid
)


def test_extract_calendar_features():
    # 2022-06-01T05:00:00Z is 2022-06-01 00:00:00 CDT (Wednesday, weekday=2)
    dt_utc = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
    feats = extract_calendar_features(dt_utc)
    assert feats["hour_of_day"] == 0.0
    assert feats["day_of_week"] == 2.0  # Wednesday
    assert feats["is_weekend"] == 0.0
    assert np.isclose(feats["sin_hour"], 0.0)
    assert np.isclose(feats["cos_hour"], 1.0)

    # Saturday 14:00 CDT = 19:00 UTC
    dt_sat = datetime(2022, 6, 4, 19, 0, 0, tzinfo=timezone.utc)
    feats_sat = extract_calendar_features(dt_sat)
    assert feats_sat["hour_of_day"] == 14.0
    assert feats_sat["day_of_week"] == 5.0  # Saturday
    assert feats_sat["is_weekend"] == 1.0


def test_features_no_lookahead_contract():
    """
    CRITICAL CONTRACT TEST:
    Modifying or inserting events into the future (at or after origin T)
    MUST NOT alter any feature computed at origin T.
    """
    start = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 10, 5, 0, 0, tzinfo=timezone.utc)  # 9 days
    zones = ["zone_A", "zone_B"]
    zone_means = {"zone_A": 12.5, "zone_B": 4.0}

    # Generate complete baseline grid with deterministic synthetic values
    windows = generate_window_grid(start, end, 15)
    rows = []
    for i, w in enumerate(windows):
        rows.append({"window_start": w, "h3_cell": "zone_A", "ride_count": (i % 10), "demand_status": "HISTORICAL_OBSERVED"})
        rows.append({"window_start": w, "h3_cell": "zone_B", "ride_count": (i % 5), "demand_status": "HISTORICAL_OBSERVED"})
    grid_original = pd.DataFrame(rows)
    grid_original["window_end"] = grid_original["window_start"] + timedelta(minutes=15)

    # Prediction origin T at Day 8 (2022-06-09T05:00:00Z)
    origin_T = datetime(2022, 6, 9, 5, 0, 0, tzinfo=timezone.utc)

    # 1. Compute features with original data
    feats_before = build_feature_table_for_origin(grid_original, origin_T, zones, zone_means)

    # 2. Corrupt/mutate future data (at T, T+15m, T+30m, T+1day) with extreme values (surges, zeros, etc.)
    grid_corrupted = grid_original.copy()
    future_mask = grid_corrupted["window_start"] >= origin_T
    grid_corrupted.loc[future_mask, "ride_count"] = 999999  # extreme surge in future

    # 3. Recompute features at origin T with corrupted future
    feats_after = build_feature_table_for_origin(grid_corrupted, origin_T, zones, zone_means)

    # Assert exact equality across all feature columns
    for col in FEATURE_COLUMNS:
        np.testing.assert_array_equal(
            feats_before[col].values,
            feats_after[col].values,
            err_msg=f"Feature {col} leaked future data! Values changed after future mutation."
        )


def test_build_full_feature_matrix_consistency():
    start = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 9, 5, 0, 0, tzinfo=timezone.utc)  # 8 days
    zones = ["zone_A"]

    windows = generate_window_grid(start, end, 15)
    rows = []
    for i, w in enumerate(windows):
        rows.append({"window_start": w, "h3_cell": "zone_A", "ride_count": 5, "demand_status": "HISTORICAL_OBSERVED"})
    grid = pd.DataFrame(rows)
    grid["window_end"] = grid["window_start"] + timedelta(minutes=15)

    origin = datetime(2022, 6, 8, 5, 0, 0, tzinfo=timezone.utc)
    matrix = build_full_feature_matrix(grid, [origin], zones, {"zone_A": 5.0})

    assert len(matrix) == 1
    row = matrix.iloc[0]
    assert row["lag_15m"] == 5.0
    assert row["lag_30m"] == 5.0
    assert row["demand_prev_30m"] == 10.0
    assert row["rolling_mean_1h"] == 5.0
    assert row["lag_24h"] == 10.0
    assert row["lag_7d"] == 10.0

