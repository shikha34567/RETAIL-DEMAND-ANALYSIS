"""
Unit tests for supply simulation module (pipeline/simulation/supply.py).
"""

import pytest
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from pipeline.simulation.supply import (
    SupplySimulator,
    get_time_of_day_supply_multiplier
)
from pipeline.simulation import SOURCE_TYPE, SUPPLY_DATA_STATUS


def test_time_of_day_multiplier_bounds():
    # 4 AM UTC = 23:00 CDT previous day
    # Check bounds [0.35, 0.90]
    for h in range(24):
        dt = datetime(2022, 6, 22, h, 0, 0, tzinfo=timezone.utc)
        m = get_time_of_day_supply_multiplier(dt)
        assert 0.35 <= m <= 0.90


def test_supply_simulation_determinism():
    """
    CRITICAL CONTRACT TEST:
    Given the same seed and inputs, simulation MUST produce identical outputs.
    """
    zones = ["zone_A", "zone_B", "zone_C"]
    weights = {"zone_A": 10.0, "zone_B": 5.0, "zone_C": 1.0}
    origin = datetime(2022, 6, 22, 14, 0, 0, tzinfo=timezone.utc)

    sim1 = SupplySimulator(eligible_zones=zones, zone_historical_weights=weights, random_seed=42)
    out1 = sim1.simulate_origin_supply(origin)

    sim2 = SupplySimulator(eligible_zones=zones, zone_historical_weights=weights, random_seed=42)
    out2 = sim2.simulate_origin_supply(origin)

    pd.testing.assert_frame_equal(out1, out2)

    # Different seed produces different distribution
    sim3 = SupplySimulator(eligible_zones=zones, zone_historical_weights=weights, random_seed=999)
    out3 = sim3.simulate_origin_supply(origin)
    assert not (out1["simulated_available_vehicles"].values == out3["simulated_available_vehicles"].values).all()


def test_supply_capacity_alignment():
    zones = ["zone_A"]
    origin = datetime(2022, 6, 22, 14, 0, 0, tzinfo=timezone.utc)
    sim = SupplySimulator(eligible_zones=zones, fleet_size=100, capacity_rate_r=2.5, random_seed=42)
    res = sim.simulate_origin_supply(origin)

    assert len(res) == 1
    row = res.iloc[0]
    v = row["available_vehicles_V"]
    c = row["estimated_capacity_C"]
    assert c == v * 2.5
    assert row["source_type"] == SOURCE_TYPE
    assert row["supply_data_status"] == SUPPLY_DATA_STATUS

