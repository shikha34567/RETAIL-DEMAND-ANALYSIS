"""
Unit tests for forecasting baseline models.
"""

import pytest
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from pipeline.forecasting.baselines import (
    PreviousWindowBaseline,
    SeasonalNaiveBaseline
)


def test_previous_window_baseline():
    model = PreviousWindowBaseline()
    
    # Feature-based prediction
    feats = pd.DataFrame({
        "demand_prev_30m": [15.0, 0.0, -2.0, np.nan]
    })
    preds = model.predict_from_features(feats)
    assert preds.iloc[0] == 15.0
    assert preds.iloc[1] == 0.0
    assert preds.iloc[2] == 0.0  # clipped
    assert preds.iloc[3] == 0.0  # filled NaN

    # Origin-based prediction from grid
    origin = datetime(2022, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    w_30m = origin - timedelta(minutes=30)
    w_15m = origin - timedelta(minutes=15)

    grid = pd.DataFrame([
        {"window_start": w_30m, "h3_cell": "zone_A", "ride_count": 8},
        {"window_start": w_15m, "h3_cell": "zone_A", "ride_count": 12},
    ])
    res = model.predict_for_origin(grid, origin, ["zone_A", "zone_B"])
    assert len(res) == 2
    row_a = res[res["h3_cell"] == "zone_A"].iloc[0]
    assert row_a["predicted_rides"] == 20.0

    row_b = res[res["h3_cell"] == "zone_B"].iloc[0]
    assert row_b["predicted_rides"] == 0.0


def test_seasonal_naive_baseline():
    model = SeasonalNaiveBaseline()

    # Feature-based prediction
    feats = pd.DataFrame({
        "lag_7d": [25.0, 0.0, np.nan]
    })
    preds = model.predict_from_features(feats)
    assert preds.iloc[0] == 25.0
    assert preds.iloc[1] == 0.0
    assert np.isnan(preds.iloc[2])

    # Origin-based prediction with full history
    origin = datetime(2022, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    t_7d_0 = origin - timedelta(days=7)
    t_7d_1 = t_7d_0 + timedelta(minutes=15)

    grid = pd.DataFrame([
        {"window_start": t_7d_0, "h3_cell": "zone_A", "ride_count": 14},
        {"window_start": t_7d_1, "h3_cell": "zone_A", "ride_count": 16},
    ])
    res = model.predict_for_origin(grid, origin, ["zone_A", "zone_B"])
    row_a = res[res["h3_cell"] == "zone_A"].iloc[0]
    assert row_a["predicted_rides"] == 30.0

    # Zone B has missing history -> NaN
    row_b = res[res["h3_cell"] == "zone_B"].iloc[0]
    assert np.isnan(row_b["predicted_rides"])

