"""
RideIntel Feature Engineering Module.

Constructs feature matrices at prediction origin T strictly using observations
at or before T (no-lookahead contract).
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
import zoneinfo
import numpy as np
import pandas as pd

CHICAGO_TZ = zoneinfo.ZoneInfo("America/Chicago")


FEATURE_COLUMNS = [
    "lag_15m",
    "lag_30m",
    "lag_45m",
    "lag_60m",
    "demand_prev_30m",
    "rolling_mean_1h",
    "rolling_mean_4h",
    "rolling_std_4h",
    "lag_24h",
    "lag_7d",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "sin_hour",
    "cos_hour",
    "zone_historical_mean"
]


def extract_calendar_features(dt_utc: datetime) -> Dict[str, float]:
    """
    Extracts local Chicago calendar and cyclical features from a UTC datetime.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    local_dt = dt_utc.astimezone(CHICAGO_TZ)
    hour = local_dt.hour + (local_dt.minute / 60.0)
    dow = local_dt.weekday()  # 0=Monday, 6=Sunday
    is_weekend = 1.0 if dow in (5, 6) else 0.0

    sin_hour = np.sin(2 * np.pi * hour / 24.0)
    cos_hour = np.cos(2 * np.pi * hour / 24.0)

    return {
        "hour_of_day": float(local_dt.hour),
        "day_of_week": float(dow),
        "is_weekend": is_weekend,
        "sin_hour": float(sin_hour),
        "cos_hour": float(cos_hour)
    }


def build_feature_table_for_origin(
    demand_grid: pd.DataFrame,
    origin_utc: datetime,
    eligible_zones: List[str],
    zone_means: Optional[Dict[str, float]] = None
) -> pd.DataFrame:
    """
    Extracts features for all eligible zones at a single prediction origin T.
    
    CRITICAL: Uses ONLY data with window_end <= origin_utc.
    """
    if origin_utc.tzinfo is None:
        origin_utc = origin_utc.replace(tzinfo=timezone.utc)

    # Filter demand grid strictly to history prior to origin
    history = demand_grid[demand_grid["window_end"] <= origin_utc]

    # Quick index lookup using pivot
    pivot = history.pivot(index="window_start", columns="h3_cell", values="ride_count").sort_index()

    # Required lag timestamps (window_start times)
    w_15m = origin_utc - timedelta(minutes=15)
    w_30m = origin_utc - timedelta(minutes=30)
    w_45m = origin_utc - timedelta(minutes=45)
    w_60m = origin_utc - timedelta(minutes=60)
    
    # 24h lag for 30m window = sum of [T - 24h, T - 24h + 15m) and [T - 24h + 15m, T - 24h + 30m)
    t_24h_0 = origin_utc - timedelta(hours=24)
    t_24h_1 = t_24h_0 + timedelta(minutes=15)

    # 7d lag for 30m window = sum of [T - 7d, T - 7d + 15m) and [T - 7d + 15m, T - 7d + 30m)
    t_7d_0 = origin_utc - timedelta(days=7)
    t_7d_1 = t_7d_0 + timedelta(minutes=15)

    calendar_feats = extract_calendar_features(origin_utc)

    rows = []
    for zone in eligible_zones:
        # Lag 15m
        v_15m = float(pivot.at[w_15m, zone]) if (w_15m in pivot.index and zone in pivot.columns) else 0.0
        # Lag 30m
        v_30m = float(pivot.at[w_30m, zone]) if (w_30m in pivot.index and zone in pivot.columns) else 0.0
        # Lag 45m
        v_45m = float(pivot.at[w_45m, zone]) if (w_45m in pivot.index and zone in pivot.columns) else 0.0
        # Lag 60m
        v_60m = float(pivot.at[w_60m, zone]) if (w_60m in pivot.index and zone in pivot.columns) else 0.0

        prev_30m = v_15m + v_30m

        # Rolling 1h (last 4 windows)
        last_4_windows = [origin_utc - timedelta(minutes=15 * i) for i in range(1, 5)]
        vals_1h = [float(pivot.at[w, zone]) for w in last_4_windows if (w in pivot.index and zone in pivot.columns)]
        mean_1h = float(np.mean(vals_1h)) if vals_1h else 0.0

        # Rolling 4h (last 16 windows)
        last_16_windows = [origin_utc - timedelta(minutes=15 * i) for i in range(1, 17)]
        vals_4h = [float(pivot.at[w, zone]) for w in last_16_windows if (w in pivot.index and zone in pivot.columns)]
        mean_4h = float(np.mean(vals_4h)) if vals_4h else 0.0
        std_4h = float(np.std(vals_4h)) if vals_4h else 0.0

        # Lag 24h (30 min sum)
        val_24h_0 = float(pivot.at[t_24h_0, zone]) if (t_24h_0 in pivot.index and zone in pivot.columns) else np.nan
        val_24h_1 = float(pivot.at[t_24h_1, zone]) if (t_24h_1 in pivot.index and zone in pivot.columns) else np.nan
        lag_24h = (val_24h_0 + val_24h_1) if (not np.isnan(val_24h_0) and not np.isnan(val_24h_1)) else np.nan

        # Lag 7d (30 min sum)
        val_7d_0 = float(pivot.at[t_7d_0, zone]) if (t_7d_0 in pivot.index and zone in pivot.columns) else np.nan
        val_7d_1 = float(pivot.at[t_7d_1, zone]) if (t_7d_1 in pivot.index and zone in pivot.columns) else np.nan
        lag_7d = (val_7d_0 + val_7d_1) if (not np.isnan(val_7d_0) and not np.isnan(val_7d_1)) else np.nan

        z_mean = zone_means.get(zone, 0.0) if zone_means else 0.0

        row = {
            "origin": origin_utc,
            "h3_cell": zone,
            "lag_15m": v_15m,
            "lag_30m": v_30m,
            "lag_45m": v_45m,
            "lag_60m": v_60m,
            "demand_prev_30m": prev_30m,
            "rolling_mean_1h": mean_1h,
            "rolling_mean_4h": mean_4h,
            "rolling_std_4h": std_4h,
            "lag_24h": lag_24h,
            "lag_7d": lag_7d,
            "zone_historical_mean": z_mean,
            **calendar_feats
        }
        rows.append(row)

    return pd.DataFrame(rows)


def build_full_feature_matrix(
    demand_grid: pd.DataFrame,
    origins: List[datetime],
    eligible_zones: List[str],
    zone_means: Optional[Dict[str, float]] = None
) -> pd.DataFrame:
    """
    Constructs the feature matrix across a sequence of origins in vectorized / chunked format.
    Ensures strict no-lookahead by shifting past demand matrix.
    """
    pivot = demand_grid.pivot(index="window_start", columns="h3_cell", values="ride_count").sort_index()

    # Pre-compute lag and rolling matrices for all windows
    # Since windows are strictly every 15m:
    # lag 15m = shift(1)
    # lag 30m = shift(2)
    # lag 45m = shift(3)
    # lag 60m = shift(4)
    # lag 24h = shift(96) + shift(95) -> [T-24h, T-24h+15m) + [T-24h+15m, T-24h+30m)
    # lag 7d  = shift(672) + shift(671) -> 7 days * 96 windows/day = 672
    lag_1 = pivot.shift(1)
    lag_2 = pivot.shift(2)
    lag_3 = pivot.shift(3)
    lag_4 = pivot.shift(4)

    demand_prev_30m = lag_1 + lag_2
    rolling_1h = (lag_1 + lag_2 + lag_3 + lag_4) / 4.0

    # Rolling 4h over the 16 past windows (shift 1 through 16)
    rolling_4h_sum = sum(pivot.shift(i) for i in range(1, 17))
    rolling_4h_mean = rolling_4h_sum / 16.0

    # Rolling 4h variance / std
    shifted_4h = [pivot.shift(i) for i in range(1, 17)]
    # Compute std across the 16 frames
    concat_4h = pd.concat([s.stack() for s in shifted_4h], axis=1)
    rolling_4h_std = concat_4h.std(axis=1).unstack()

    lag_24h = pivot.shift(96) + pivot.shift(95)
    lag_7d = pivot.shift(672) + pivot.shift(671)

    dfs = []
    for origin in origins:
        if origin not in pivot.index:
            continue
        
        cal = extract_calendar_features(origin)
        
        row_df = pd.DataFrame({
            "origin": origin,
            "h3_cell": eligible_zones,
            "lag_15m": lag_1.loc[origin, eligible_zones].values,
            "lag_30m": lag_2.loc[origin, eligible_zones].values,
            "lag_45m": lag_3.loc[origin, eligible_zones].values,
            "lag_60m": lag_4.loc[origin, eligible_zones].values,
            "demand_prev_30m": demand_prev_30m.loc[origin, eligible_zones].values,
            "rolling_mean_1h": rolling_1h.loc[origin, eligible_zones].values,
            "rolling_mean_4h": rolling_4h_mean.loc[origin, eligible_zones].values,
            "rolling_std_4h": rolling_4h_std.loc[origin, eligible_zones].values,
            "lag_24h": lag_24h.loc[origin, eligible_zones].values,
            "lag_7d": lag_7d.loc[origin, eligible_zones].values,
            "hour_of_day": cal["hour_of_day"],
            "day_of_week": cal["day_of_week"],
            "is_weekend": cal["is_weekend"],
            "sin_hour": cal["sin_hour"],
            "cos_hour": cal["cos_hour"],
            "zone_historical_mean": [zone_means.get(z, 0.0) if zone_means else 0.0 for z in eligible_zones]
        })
        dfs.append(row_df)

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)

