"""
RideIntel Forecasting Package.

Implements demand aggregation, feature extraction, baselines,
XGBoost model training, and chronological evaluation.
"""

from typing import List, Tuple
from datetime import datetime, timezone

# Canonical Split Timestamps (UTC)
DATASET_START_UTC = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
TRAIN_VAL_SPLIT_UTC = datetime(2022, 6, 15, 5, 0, 0, tzinfo=timezone.utc)
TRAIN_TEST_SPLIT_UTC = datetime(2022, 6, 22, 5, 0, 0, tzinfo=timezone.utc)
DATASET_END_UTC = datetime(2022, 7, 1, 5, 0, 0, tzinfo=timezone.utc)

WINDOW_MINUTES = 15
HORIZON_MINUTES = 30
MIN_HISTORICAL_TRIPS = 10
TARGET_RESOLUTION = 8

