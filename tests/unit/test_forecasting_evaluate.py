"""
Unit tests for forecasting evaluation metrics and identical-row evaluation contract.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from pipeline.forecasting.evaluate import (
    compute_metrics,
    evaluate_models_on_identical_rows,
    compute_metrics_by_group
)


def test_compute_metrics_standard():
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 18.0, 35.0])
    # diff: [2, 2, 5]
    # MAE = (2 + 2 + 5) / 3 = 3.0
    # squared diff: [4, 4, 25] -> mean 11.0 -> RMSE = sqrt(11) = 3.3166
    # WAPE = 9 / 60 = 0.15 (15%)

    res = compute_metrics(y_true, y_pred)
    assert res["count"] == 3
    assert np.isclose(res["mae"], 3.0)
    assert np.isclose(res["rmse"], np.sqrt(11.0))
    assert np.isclose(res["wape"], 0.15)
    assert res["wape_status"] == "VALID"


def test_wape_undefined_zero_actual_contract():
    """
    CRITICAL CONTRACT TEST (AGENTS.md & parquet_schemas.md):
    If sum(actual) = 0, WAPE is undefined: write wape = null and wape_status = 'UNDEFINED_ZERO_ACTUAL'.
    Never write 0 or invent a value.
    """
    y_true = np.array([0.0, 0.0, 0.0])
    y_pred = np.array([2.0, 1.0, 0.0])

    res = compute_metrics(y_true, y_pred)
    assert res["count"] == 3
    assert res["sum_actual"] == 0.0
    assert res["mae"] == 1.0
    assert res["wape"] is None  # MUST BE NULL
    assert res["wape_status"] == "UNDEFINED_ZERO_ACTUAL"


def test_evaluate_models_on_identical_rows():
    origin_1 = datetime(2022, 6, 22, 5, 0, 0, tzinfo=timezone.utc)
    origin_2 = datetime(2022, 6, 22, 5, 15, 0, tzinfo=timezone.utc)

    # 2 origins, 1 zone -> 2 candidate pairs: (origin_1, zA) and (origin_2, zA)
    # Suppose for origin_2, model_B has NaN (missing history)
    rows = [
        # Pair 1: All valid
        {"origin": origin_1, "h3_cell": "zA", "target_start": origin_1, "target_end": origin_1 + timedelta(minutes=30), "actual_rides": 10, "model_name": "model_A", "predicted_rides": 12.0},
        {"origin": origin_1, "h3_cell": "zA", "target_start": origin_1, "target_end": origin_1 + timedelta(minutes=30), "actual_rides": 10, "model_name": "model_B", "predicted_rides": 11.0},
        # Pair 2: model_B has NaN
        {"origin": origin_2, "h3_cell": "zA", "target_start": origin_2, "target_end": origin_2 + timedelta(minutes=30), "actual_rides": 5, "model_name": "model_A", "predicted_rides": 6.0},
        {"origin": origin_2, "h3_cell": "zA", "target_start": origin_2, "target_end": origin_2 + timedelta(minutes=30), "actual_rides": 5, "model_name": "model_B", "predicted_rides": np.nan},
    ]
    eval_df = pd.DataFrame(rows)

    filtered_df, summary = evaluate_models_on_identical_rows(eval_df, ["model_A", "model_B"])

    assert summary["total_candidate_pairs"] == 2
    assert summary["retained_identical_pairs"] == 1
    assert summary["dropped_pairs"] == 1

    # Both models must have exactly 1 row in filtered_df
    assert len(filtered_df[filtered_df["model_name"] == "model_A"]) == 1
    assert len(filtered_df[filtered_df["model_name"] == "model_B"]) == 1
    assert filtered_df["origin"].iloc[0] == origin_1

