"""
RideIntel Training-Window Zone Eligibility Derivation.

Derives operational H3 zones using strictly pre-split training data
to prevent temporal lookahead leakage during model training and evaluation.
"""

import os
from typing import Set, List, Dict, Any, Optional
from datetime import datetime, timezone
from collections import Counter
import pyarrow.parquet as pq
import pyarrow.compute as pc

from pipeline.spatial.h3_index import coords_to_h3
from pipeline.forecasting import (
    TRAIN_TEST_SPLIT_UTC,
    MIN_HISTORICAL_TRIPS,
    TARGET_RESOLUTION
)

DEFAULT_CLEANED_PARQUET = os.path.join("data", "interim", "cleaned_trips_2022-06", "cleaned_trips.parquet")


def derive_training_eligible_zones(
    parquet_path: str = DEFAULT_CLEANED_PARQUET,
    split_cutoff_utc: datetime = TRAIN_TEST_SPLIT_UTC,
    min_trips: int = MIN_HISTORICAL_TRIPS,
    resolution: int = TARGET_RESOLUTION
) -> Dict[str, Any]:
    """
    Computes operational H3 cells using only trips occurring strictly before split_cutoff_utc.

    Returns a dictionary with:
      - 'eligible_zones': sorted list of H3 cell strings
      - 'zone_counts': dict of {h3_cell: training_trip_count}
      - 'total_train_trips': int
      - 'retained_train_trips': int
      - 'split_cutoff_utc': ISO format string
    """
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"Cleaned Parquet dataset not found at: {parquet_path}")

    # Read needed columns
    table = pq.read_table(
        parquet_path,
        columns=["event_ts", "pickup_centroid_latitude", "pickup_centroid_longitude"]
    )

    # Filter strictly prior to split_cutoff_utc
    ts_col = table["event_ts"]
    train_mask = pc.less(ts_col, split_cutoff_utc)
    train_table = table.filter(train_mask)

    total_train_trips = train_table.num_rows

    latitudes = train_table["pickup_centroid_latitude"].to_pylist()
    longitudes = train_table["pickup_centroid_longitude"].to_pylist()

    cells: List[str] = []
    for lat, lon in zip(latitudes, longitudes):
        cell = coords_to_h3(lat, lon, resolution=resolution)
        if cell is not None:
            cells.append(cell)

    zone_counts = dict(Counter(cells))
    eligible_zones = sorted([cell for cell, count in zone_counts.items() if count >= min_trips])
    retained_train_trips = sum(zone_counts[c] for c in eligible_zones)

    return {
        "eligible_zones": eligible_zones,
        "eligible_zone_count": len(eligible_zones),
        "total_observed_zones": len(zone_counts),
        "zone_counts": zone_counts,
        "total_train_trips": total_train_trips,
        "retained_train_trips": retained_train_trips,
        "split_cutoff_utc": split_cutoff_utc.isoformat(),
        "min_trips_threshold": min_trips,
        "resolution": resolution
    }


def identify_leaked_zones(
    training_eligible_zones: Set[str],
    full_month_universe_path: str = os.path.join("data", "processed", "zone_universe", "zone_universe.parquet")
) -> List[str]:
    """
    Identifies zones that were flagged as operational retrospectively across the full month,
    but had < min_trips during the training period.
    """
    if not os.path.exists(full_month_universe_path):
        return []

    table = pq.read_table(full_month_universe_path)
    pydict = table.to_pydict()
    full_month_operational = set(
        cell for cell, is_op in zip(pydict["h3_cell"], pydict["is_operational_universe"]) if is_op
    )

    leaked = sorted(list(full_month_operational - training_eligible_zones))
    return leaked
