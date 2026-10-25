"""
RideIntel Baseline Forecasting Models.

Implements:
1. Previous-Window Baseline (baseline_rolling_avg):
   Predicts demand in [T, T + 30m) as the demand observed in [T - 30m, T).
2. Seasonal-Naive Baseline (baseline_same_time_last_week):
   Predicts demand in [T, T + 30m) as the demand observed at the same time last week [T - 7d, T - 7d + 30m).
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np


class PreviousWindowBaseline:
    """
    Baseline model that predicts demand over the forward 30-minute horizon [T, T + 30m)
    using the sum of the previous two 15-minute windows [T - 30m, T).
    """

    def __init__(self, model_name: str = "baseline_rolling_avg", model_version: str = "v1.0.0"):
        self.model_name = model_name
        self.model_version = model_version

    def predict_from_features(self, feature_df: pd.DataFrame) -> pd.Series:
        """
        Predicts from feature DataFrame using 'demand_prev_30m'.
        Ensures non-negative predictions.
        """
        if "demand_prev_30m" not in feature_df.columns:
            raise KeyError("Feature 'demand_prev_30m' missing from input features.")
        preds = feature_df["demand_prev_30m"].fillna(0.0).clip(lower=0.0)
        return preds

    def predict_for_origin(
        self,
        demand_grid: pd.DataFrame,
        origin_utc: datetime,
        eligible_zones: List[str]
    ) -> pd.DataFrame:
        """
        Generates predictions for all eligible zones at origin_utc directly from demand grid.
        """
        w_15m = origin_utc - timedelta(minutes=15)
        w_30m = origin_utc - timedelta(minutes=30)

        history = demand_grid[demand_grid["window_start"].isin([w_30m, w_15m])]
        pivot = history.pivot(index="window_start", columns="h3_cell", values="ride_count").fillna(0)

        predictions = []
        for zone in eligible_zones:
            val_30 = float(pivot.at[w_30m, zone]) if (w_30m in pivot.index and zone in pivot.columns) else 0.0
            val_15 = float(pivot.at[w_15m, zone]) if (w_15m in pivot.index and zone in pivot.columns) else 0.0
            pred = max(0.0, val_30 + val_15)

            predictions.append({
                "origin": origin_utc,
                "h3_cell": zone,
                "predicted_rides": pred,
                "model_name": self.model_name,
                "model_version": self.model_version
            })

        return pd.DataFrame(predictions)


class SeasonalNaiveBaseline:
    """
    Baseline model that predicts demand over [T, T + 30m) using the observed demand
    from exactly one week prior [T - 7d, T - 7d + 30m).
    """

    def __init__(self, model_name: str = "baseline_same_time_last_week", model_version: str = "v1.0.0"):
        self.model_name = model_name
        self.model_version = model_version

    def predict_from_features(self, feature_df: pd.DataFrame) -> pd.Series:
        """
        Predicts from feature DataFrame using 'lag_7d'.
        """
        if "lag_7d" not in feature_df.columns:
            raise KeyError("Feature 'lag_7d' missing from input features.")
        preds = feature_df["lag_7d"].clip(lower=0.0)
        return preds

    def predict_for_origin(
        self,
        demand_grid: pd.DataFrame,
        origin_utc: datetime,
        eligible_zones: List[str]
    ) -> pd.DataFrame:
        """
        Generates predictions for all eligible zones at origin_utc directly from demand grid.
        """
        t_7d_0 = origin_utc - timedelta(days=7)
        t_7d_1 = t_7d_0 + timedelta(minutes=15)

        history = demand_grid[demand_grid["window_start"].isin([t_7d_0, t_7d_1])]
        pivot = history.pivot(index="window_start", columns="h3_cell", values="ride_count")

        predictions = []
        for zone in eligible_zones:
            val_0 = float(pivot.at[t_7d_0, zone]) if (t_7d_0 in pivot.index and zone in pivot.columns) else np.nan
            val_1 = float(pivot.at[t_7d_1, zone]) if (t_7d_1 in pivot.index and zone in pivot.columns) else np.nan

            if np.isnan(val_0) or np.isnan(val_1):
                pred = np.nan
            else:
                pred = max(0.0, val_0 + val_1)

            predictions.append({
                "origin": origin_utc,
                "h3_cell": zone,
                "predicted_rides": pred,
                "model_name": self.model_name,
                "model_version": self.model_version
            })

        return pd.DataFrame(predictions)

