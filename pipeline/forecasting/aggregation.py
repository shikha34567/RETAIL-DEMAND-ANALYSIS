"""
RideIntel 15-Minute Window Aggregation & Completeness Policy.

Aggregates historical trips into 15-minute tumbling windows, enforces explicit
window completeness checks, zero-fills complete windows against eligible zones,
and derives 30-minute forward target demands.
"""

import os
from typing import List, Dict, Tuple, Set, Optional, Iterator
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
import pyarrow.compute as pc

from pipeline.spatial.h3_index import coords_to_h3
from pipeline.forecasting import (
    DATASET_START_UTC,
    DATASET_END_UTC,
    WINDOW_MINUTES,
    HORIZON_MINUTES,
    TARGET_RESOLUTION
)

DEFAULT_CLEANED_PARQUET = os.path.join("data", "interim", "cleaned_trips_2022-06", "cleaned_trips.parquet")


def floor_to_window(dt: datetime, window_minutes: int = WINDOW_MINUTES) -> datetime:
    """Floors a datetime to the nearest tumbling window boundary in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    
    total_minutes = dt.hour * 60 + dt.minute
    floored_minutes = (total_minutes // window_minutes) * window_minutes
    hour = floored_minutes // 60
    minute = floored_minutes % 60
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)


def generate_window_grid(
    start_utc: datetime = DATASET_START_UTC,
    end_utc: datetime = DATASET_END_UTC,
    window_minutes: int = WINDOW_MINUTES
) -> List[datetime]:
    """Generates the continuous list of tumbling window start datetimes in [start_utc, end_utc)."""
    grid = []
    current = start_utc
    delta = timedelta(minutes=window_minutes)
    while current < end_utc:
        grid.append(current)
        current += delta
    return grid


def is_window_complete(
    window_start: datetime,
    dataset_start: datetime = DATASET_START_UTC,
    dataset_end: datetime = DATASET_END_UTC,
    window_minutes: int = WINDOW_MINUTES
) -> bool:
    """
    Evaluates whether a 15-minute window [window_start, window_start + window_minutes)
    is completely contained within the continuous observation boundaries of the dataset.
    """
    window_end = window_start + timedelta(minutes=window_minutes)
    return (window_start >= dataset_start) and (window_end <= dataset_end)


def aggregate_observed_trips(
    parquet_path: str = DEFAULT_CLEANED_PARQUET,
    resolution: int = TARGET_RESOLUTION,
    window_minutes: int = WINDOW_MINUTES,
    filter_eligible_zones: Optional[Set[str]] = None
) -> pd.DataFrame:
    """
    Reads cleaned trips, indexes them to H3 cells, and aggregates positive trip counts
    by (window_start, h3_cell).
    """
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"Cleaned Parquet dataset not found at: {parquet_path}")

    table = pq.read_table(
        parquet_path,
        columns=["event_ts", "pickup_centroid_latitude", "pickup_centroid_longitude"]
    )

    df = table.to_pandas()
    
    # Assign H3 cell
    df["h3_cell"] = [
        coords_to_h3(lat, lon, resolution=resolution)
        for lat, lon in zip(df["pickup_centroid_latitude"], df["pickup_centroid_longitude"])
    ]
    df = df.dropna(subset=["h3_cell"])

    if filter_eligible_zones is not None:
        df = df[df["h3_cell"].isin(filter_eligible_zones)]

    # Floor event timestamp to 15m window start
    # Using vectorized pandas dt operations for speed
    df["window_start"] = df["event_ts"].dt.floor(f"{window_minutes}min")

    agg = (
        df.groupby(["window_start", "h3_cell"])
        .size()
        .reset_index(name="ride_count")
    )
    agg["window_end"] = agg["window_start"] + timedelta(minutes=window_minutes)
    return agg


def create_zero_filled_demand_grid(
    observed_agg: pd.DataFrame,
    eligible_zones: List[str],
    start_utc: datetime = DATASET_START_UTC,
    end_utc: datetime = DATASET_END_UTC,
    window_minutes: int = WINDOW_MINUTES
) -> pd.DataFrame:
    """
    Zero-fills complete 15-minute windows strictly against the specified eligible_zones.
    
    Returns a DataFrame with columns:
      ['window_start', 'window_end', 'h3_cell', 'ride_count', 'demand_status']
    """
    windows = generate_window_grid(start_utc=start_utc, end_utc=end_utc, window_minutes=window_minutes)
    
    # Construct Cartesian product of (windows, eligible_zones)
    idx = pd.MultiIndex.from_product(
        [windows, eligible_zones],
        names=["window_start", "h3_cell"]
    )
    grid_df = pd.DataFrame(index=idx).reset_index()
    grid_df["window_end"] = grid_df["window_start"] + timedelta(minutes=window_minutes)

    # Merge observed counts
    merged = pd.merge(
        grid_df,
        observed_agg[["window_start", "h3_cell", "ride_count"]],
        on=["window_start", "h3_cell"],
        how="left"
    )

    # Status labelling
    merged["demand_status"] = np.where(
        merged["ride_count"].notna(),
        "HISTORICAL_OBSERVED",
        "ZERO_FILLED_COMPLETE_WINDOW"
    )
    merged["ride_count"] = merged["ride_count"].fillna(0).astype(np.int64)

    return merged.sort_values(["window_start", "h3_cell"]).reset_index(drop=True)


def compute_target_demand(
    demand_grid: pd.DataFrame,
    horizon_minutes: int = HORIZON_MINUTES,
    window_minutes: int = WINDOW_MINUTES
) -> pd.DataFrame:
    """
    At each origin T = window_start, computes target demand:
    Y(z, T) = ride_count(z, [T, T + 15m)) + ride_count(z, [T + 15m, T + 30m))
    
    Returns DataFrame indexed by (origin, h3_cell) with target_demand (float64/int64).
    Excludes origins whose target horizon extends beyond the complete dataset boundary.
    """
    steps = horizon_minutes // window_minutes
    if steps != 2:
        raise ValueError(f"Target calculation currently configured for 2 windows (30m / 15m), got {steps}")

    # Pivot to wide format: rows=window_start, cols=h3_cell
    pivot = demand_grid.pivot(index="window_start", columns="h3_cell", values="ride_count").sort_index()

    # Target is forward sum of next 2 windows starting at T:
    # W1 is at T (shift 0), W2 is at T + 15m (shift -1)
    target_matrix = pivot + pivot.shift(-1)

    # Drop any row where shift(-1) was NaN (i.e. the last window, which lacks the second 15m window)
    target_matrix = target_matrix.dropna()

    # Melt back to long format
    target_long = (
        target_matrix.reset_index()
        .melt(id_vars=["window_start"], var_name="h3_cell", value_name="target_rides_30m")
        .rename(columns={"window_start": "origin"})
    )
    target_long["target_rides_30m"] = target_long["target_rides_30m"].astype(np.int64)
    target_long["target_start"] = target_long["origin"]
    target_long["target_end"] = target_long["origin"] + timedelta(minutes=horizon_minutes)
    
    return target_long.sort_values(["origin", "h3_cell"]).reset_index(drop=True)
