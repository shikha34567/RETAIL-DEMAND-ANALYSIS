"""
RideIntel Supply Simulation Module.

Simulates time-varying available vehicle fleets across operational H3 zones
at prediction origin T using strictly causal, pre-split priors.

LABELLING:
All generated supply outputs are labelled as SIMULATED or SIMULATED_ESTIMATE.
This module does not represent observed real-world fleet inventory.
"""

from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, timezone
import zoneinfo
import numpy as np
import pandas as pd

from pipeline.simulation import SOURCE_TYPE, SUPPLY_DATA_STATUS

CHICAGO_TZ = zoneinfo.ZoneInfo("America/Chicago")

DEFAULT_FLEET_SIZE = 2500
DEFAULT_AVAILABILITY_RATIO = 0.60
DEFAULT_CAPACITY_RATE = 2.0  # rides per vehicle per 30 minutes
DEFAULT_SEED = 42


def get_time_of_day_supply_multiplier(dt_utc: datetime) -> float:
    """
    Computes a time-of-day driver supply availability multiplier based on local Chicago time.
    Troughs in early morning (~0.40 at 4 AM) and peaks during evening commute (~0.85 at 6 PM).
    Derived purely from origin timestamp without lookahead.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    local_dt = dt_utc.astimezone(CHICAGO_TZ)
    hour = local_dt.hour + (local_dt.minute / 60.0)

    # Parametric diurnal curve: base 0.60, amplitude 0.25, peak at 18:00 (hour 18)
    # cos((hour - 18) * 2pi / 24)
    multiplier = 0.60 + 0.25 * np.cos((hour - 18.0) * 2.0 * np.pi / 24.0)
    return float(np.clip(multiplier, 0.35, 0.90))


class SupplySimulator:
    """
    Stochastic, seeded vehicle supply simulator across eligible H3 zones.
    """

    def __init__(
        self,
        eligible_zones: List[str],
        zone_historical_weights: Optional[Dict[str, float]] = None,
        fleet_size: int = DEFAULT_FLEET_SIZE,
        base_availability_ratio: float = DEFAULT_AVAILABILITY_RATIO,
        capacity_rate_r: float = DEFAULT_CAPACITY_RATE,
        random_seed: int = DEFAULT_SEED
    ):
        self.eligible_zones = sorted(eligible_zones)
        self.fleet_size = fleet_size
        self.base_availability_ratio = base_availability_ratio
        self.capacity_rate_r = capacity_rate_r
        self.random_seed = random_seed

        # Build baseline spatial probability distribution
        # If no weights given, uniform; otherwise normalized from historical training priors
        if zone_historical_weights:
            raw_weights = np.array([zone_historical_weights.get(z, 0.1) for z in self.eligible_zones], dtype=float)
            # Add small Dirichlet/smoothing prior so all zones have chance of vehicles
            raw_weights = np.maximum(raw_weights, 0.05)
            self.spatial_probs = raw_weights / np.sum(raw_weights)
        else:
            self.spatial_probs = np.ones(len(self.eligible_zones)) / len(self.eligible_zones)

    def simulate_origin_supply(
        self,
        origin_utc: datetime,
        simulation_run_id: str = "sim-run-001"
    ) -> pd.DataFrame:
        """
        Simulates available vehicles V and capacity C at origin_utc for all eligible zones.
        Uses a deterministic seed based on (base_seed + epoch_minutes).
        """
        if origin_utc.tzinfo is None:
            origin_utc = origin_utc.replace(tzinfo=timezone.utc)

        # Deterministic per-origin random generator
        epoch_mins = int(origin_utc.timestamp() // 60)
        origin_seed = (self.random_seed * 1000003 + epoch_mins) & 0xFFFFFFFF
        rng = np.random.default_rng(origin_seed)

        # Diurnal supply scaling
        diurnal_factor = get_time_of_day_supply_multiplier(origin_utc)
        available_fleet_total = int(np.round(self.fleet_size * diurnal_factor))

        # Multinomial allocation across zones
        zone_allocations = rng.multinomial(available_fleet_total, self.spatial_probs)

        # Build records
        records = []
        for zone, v_count in zip(self.eligible_zones, zone_allocations):
            cap_c = float(v_count) * self.capacity_rate_r
            records.append({
                "origin": origin_utc,
                "as_of": origin_utc,
                "h3_cell": zone,
                "simulated_available_vehicles": int(v_count),
                "available_vehicles_V": int(v_count),
                "capacity_rate_r": float(self.capacity_rate_r),
                "estimated_supply_capacity_rides_30m": cap_c,
                "estimated_capacity_C": cap_c,
                "source_type": SOURCE_TYPE,
                "supply_data_status": SUPPLY_DATA_STATUS,
                "simulation_run_id": simulation_run_id
            })

        return pd.DataFrame(records)

    def simulate_grid_supply(
        self,
        origins: List[datetime],
        simulation_run_id: str = "sim-run-001"
    ) -> pd.DataFrame:
        """
        Simulates supply across a sequence of origins.
        """
        frames = [self.simulate_origin_supply(o, simulation_run_id=simulation_run_id) for o in origins]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

