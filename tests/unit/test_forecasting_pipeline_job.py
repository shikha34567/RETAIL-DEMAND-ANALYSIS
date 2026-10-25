"""
Integration unit tests for the end-to-end forecasting pipeline outputs.
"""

import os
import json
import pytest
import pyarrow.parquet as pq

from pipeline.forecasting import MIN_HISTORICAL_TRIPS


def test_forecasting_artifacts_exist_and_conform():
    forecasts_path = os.path.join("data", "processed", "forecasts", "forecasts.parquet")
    eval_path = os.path.join("data", "processed", "forecasts", "forecast_evaluation.parquet")
    model_path = os.path.join("models", "xgboost_demand_model.json")
    evidence_path = os.path.join("docs", "evidence", "forecasting_evaluation_summary.json")

    assert os.path.exists(forecasts_path), f"Missing {forecasts_path}"
    assert os.path.exists(eval_path), f"Missing {eval_path}"
    assert os.path.exists(model_path), f"Missing {model_path}"
    assert os.path.exists(evidence_path), f"Missing {evidence_path}"

    # Verify forecasts schema & values
    t_fc = pq.read_table(forecasts_path)
    assert t_fc.num_rows > 0
    expected_fc_cols = {
        "forecast_id", "h3_cell", "forecast_origin", "target_start",
        "target_end", "predicted_rides", "model_name", "model_version",
        "forecast_status", "processing_run_id"
    }
    assert expected_fc_cols.issubset(set(t_fc.column_names))
    preds = t_fc["predicted_rides"].to_pylist()
    assert all(p >= 0.0 for p in preds)

    # Verify evaluation schema & values
    t_ev = pq.read_table(eval_path)
    assert t_ev.num_rows > 0
    expected_ev_cols = {
        "h3_cell", "forecast_origin", "target_start", "target_end",
        "model_name", "model_version", "predicted_rides", "actual_rides", "split"
    }
    assert expected_ev_cols.issubset(set(t_ev.column_names))

    # Verify identical counts per model
    pydict = t_ev.to_pydict()
    models = pydict["model_name"]
    from collections import Counter
    counts = Counter(models)
    assert len(counts) == 3
    assert counts["xgboost"] == counts["baseline_rolling_avg"] == counts["baseline_same_time_last_week"] == 116505

    # Verify evidence summary json
    with open(evidence_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["zone_eligibility"]["training_eligible_zones_count"] == 135
    assert summary["zone_eligibility"]["leaked_retrospective_zones_count"] == 4
    assert "xgboost" in summary["overall_evaluation"]
    assert "baseline_rolling_avg" in summary["overall_evaluation"]
    assert "baseline_same_time_last_week" in summary["overall_evaluation"]

