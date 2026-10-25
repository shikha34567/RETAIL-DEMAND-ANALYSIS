"""
RideIntel Forecast Evaluation Module.

Evaluates XGBoost and baseline models strictly on identical held-out test rows.
Calculates MAE, RMSE, and WAPE with exact zero-actual handling (UNDEFINED_ZERO_ACTUAL).
"""

from typing import List, Dict, Tuple, Optional, Any
import numpy as np
import pandas as pd


def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray
) -> Dict[str, Any]:
    """
    Computes MAE, RMSE, and WAPE.
    If sum(y_true) == 0, WAPE is null with status 'UNDEFINED_ZERO_ACTUAL'.
    """
    if len(y_true) == 0:
        return {
            "count": 0,
            "mae": None,
            "rmse": None,
            "wape": None,
            "wape_status": "EMPTY_EVALUATION_SET"
        }

    diff = np.abs(y_true - y_pred)
    mae = float(np.mean(diff))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    sum_true = float(np.sum(y_true))
    sum_diff = float(np.sum(diff))

    if sum_true == 0.0:
        wape = None
        wape_status = "UNDEFINED_ZERO_ACTUAL"
    else:
        wape = float(sum_diff / sum_true)
        wape_status = "VALID"

    return {
        "count": int(len(y_true)),
        "sum_actual": sum_true,
        "mae": mae,
        "rmse": rmse,
        "wape": wape,
        "wape_status": wape_status
    }


def evaluate_models_on_identical_rows(
    eval_df: pd.DataFrame,
    model_names: Optional[List[str]] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Enforces identical (origin, h3_cell) evaluation across all specified models.

    Input DataFrame eval_df must contain:
      ['origin', 'h3_cell', 'target_start', 'target_end', 'actual_rides', 'model_name', 'predicted_rides']

    Returns:
      - identical_eval_df: filtered evaluation DataFrame where every (origin, h3_cell)
        is present with valid, non-null predictions for all models.
      - summary_report: dict containing overall, zone-group, and hourly metrics.
    """
    required_cols = {"origin", "h3_cell", "target_start", "target_end", "actual_rides", "model_name", "predicted_rides"}
    if not required_cols.issubset(eval_df.columns):
        raise ValueError(f"eval_df missing required columns: {required_cols - set(eval_df.columns)}")

    if model_names is None:
        model_names = sorted(list(eval_df["model_name"].unique()))

    # Pivot to verify which (origin, h3_cell) pairs have non-null predictions for ALL models
    pred_pivot = eval_df.pivot(
        index=["origin", "h3_cell"],
        columns="model_name",
        values="predicted_rides"
    )

    # Valid rows must have non-null predictions for all models in model_names
    valid_mask = pred_pivot[model_names].notna().all(axis=1)
    valid_keys = pred_pivot[valid_mask].index

    # Total possible vs valid
    total_keys_count = len(pred_pivot)
    valid_keys_count = len(valid_keys)
    dropped_keys_count = total_keys_count - valid_keys_count

    # Filter eval_df to only valid_keys
    idx = pd.MultiIndex.from_tuples(valid_keys, names=["origin", "h3_cell"])
    filtered_eval = eval_df.set_index(["origin", "h3_cell"]).loc[idx].reset_index()

    # Calculate metrics per model
    overall_metrics = {}
    for model in model_names:
        sub = filtered_eval[filtered_eval["model_name"] == model]
        y_true = sub["actual_rides"].values
        y_pred = sub["predicted_rides"].values
        overall_metrics[model] = compute_metrics(y_true, y_pred)

    summary_report = {
        "models_evaluated": model_names,
        "total_candidate_pairs": total_keys_count,
        "retained_identical_pairs": valid_keys_count,
        "dropped_pairs": dropped_keys_count,
        "drop_reason": "Missing lookback or non-computable baseline prediction",
        "overall_metrics": overall_metrics
    }

    return filtered_eval, summary_report


def compute_metrics_by_group(
    identical_eval_df: pd.DataFrame,
    group_col: str,
    model_names: List[str]
) -> pd.DataFrame:
    """
    Calculates MAE, RMSE, and WAPE broken down by group_col (e.g. 'hour_of_day' or 'zone_group').
    """
    records = []
    groups = identical_eval_df[group_col].unique()

    for g in sorted(groups):
        sub_group = identical_eval_df[identical_eval_df[group_col] == g]
        for m in model_names:
            sub = sub_group[sub_group["model_name"] == m]
            m_res = compute_metrics(sub["actual_rides"].values, sub["predicted_rides"].values)
            records.append({
                group_col: g,
                "model_name": m,
                **m_res
            })

    return pd.DataFrame(records)

