"""
RideIntel Demand-Supply Pressure Calculation Module.

Aligns 30-minute demand forecast D with simulated capacity C = V x r.
Computes pressure_index (demand_supply_ratio), unserved demand, and pressure status.

Evaluates rules strictly in the order specified in contracts/parquet_schemas.md (Table 6):
1. input_status is MISSING or STALE -> UNKNOWN, index null.
2. C = 0 and D > 0 -> NO_ESTIMATED_CAPACITY, index null (never infinity).
3. C = 0 and D = 0 -> NORMAL, index 0.0.
4. C > 0: P = D / C, categorized by configured thresholds.
"""

from typing import Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from pipeline.simulation import (
    STATUS_NORMAL,
    STATUS_ELEVATED,
    STATUS_HIGH_PRESSURE,
    STATUS_NO_CAPACITY,
    STATUS_UNKNOWN,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_HIGH,
    LEVEL_CRITICAL,
    LEVEL_NO_CAPACITY,
    LEVEL_UNKNOWN,
    INPUT_STATUS_OK,
    INPUT_STATUS_MISSING,
    INPUT_STATUS_STALE,
    SUPPLY_DATA_STATUS
)

DEFAULT_ELEVATED_RATIO = 0.8
DEFAULT_HIGH_RATIO = 1.0
DEFAULT_CRITICAL_RATIO = 1.2


def evaluate_single_pressure_record(
    demand_d: Optional[float],
    vehicles_v: Optional[int],
    capacity_rate_r: float,
    elevated_ratio: float = DEFAULT_ELEVATED_RATIO,
    high_ratio: float = DEFAULT_HIGH_RATIO,
    critical_ratio: float = DEFAULT_CRITICAL_RATIO,
    input_status: str = INPUT_STATUS_OK
) -> Dict[str, Any]:
    """
    Evaluates pressure for a single (zone, origin) observation.
    Guarantees that index is NEVER infinity and unserved demand is non-negative.
    """
    # Rule 1: Missing or stale input
    if input_status in (INPUT_STATUS_MISSING, INPUT_STATUS_STALE) or demand_d is None or vehicles_v is None or np.isnan(demand_d):
        return {
            "predicted_rides_D": None if demand_d is None or np.isnan(demand_d) else float(demand_d),
            "available_vehicles_V": vehicles_v,
            "estimated_capacity_C": None,
            "pressure_index": None,
            "demand_supply_ratio": None,
            "estimated_unserved_demand_rides": None,
            "pressure_status": STATUS_UNKNOWN,
            "pressure_level": LEVEL_UNKNOWN,
            "input_status": input_status if input_status != INPUT_STATUS_OK else INPUT_STATUS_MISSING
        }

    d = float(demand_d)
    v = int(vehicles_v)
    c = float(v * capacity_rate_r)
    unserved = max(0.0, d - c)

    # Rule 2: C = 0 and D > 0 -> NO_ESTIMATED_CAPACITY, index null (Never infinity)
    if c == 0.0 and d > 0.0:
        return {
            "predicted_rides_D": d,
            "available_vehicles_V": v,
            "estimated_capacity_C": 0.0,
            "pressure_index": None,
            "demand_supply_ratio": None,
            "estimated_unserved_demand_rides": unserved,
            "pressure_status": STATUS_NO_CAPACITY,
            "pressure_level": LEVEL_NO_CAPACITY,
            "input_status": INPUT_STATUS_OK
        }

    # Rule 3: C = 0 and D = 0 -> NORMAL, index 0.0
    if c == 0.0 and d == 0.0:
        return {
            "predicted_rides_D": 0.0,
            "available_vehicles_V": 0,
            "estimated_capacity_C": 0.0,
            "pressure_index": 0.0,
            "demand_supply_ratio": 0.0,
            "estimated_unserved_demand_rides": 0.0,
            "pressure_status": STATUS_NORMAL,
            "pressure_level": LEVEL_LOW,
            "input_status": INPUT_STATUS_OK
        }

    # Rule 4: C > 0 -> P = D / C
    p = float(d / c)

    # Determine status and level
    if p >= critical_ratio:
        p_status = STATUS_HIGH_PRESSURE
        p_level = LEVEL_CRITICAL
    elif p > high_ratio:
        p_status = STATUS_HIGH_PRESSURE
        p_level = LEVEL_HIGH
    elif p >= elevated_ratio:
        p_status = STATUS_ELEVATED
        p_level = LEVEL_MODERATE
    else:
        p_status = STATUS_NORMAL
        p_level = LEVEL_LOW

    return {
        "predicted_rides_D": d,
        "available_vehicles_V": v,
        "estimated_capacity_C": c,
        "pressure_index": p,
        "demand_supply_ratio": p,
        "estimated_unserved_demand_rides": unserved,
        "pressure_status": p_status,
        "pressure_level": p_level,
        "input_status": INPUT_STATUS_OK
    }


def compute_demand_supply_pressure_table(
    forecasts_df: pd.DataFrame,
    supply_df: pd.DataFrame,
    elevated_ratio: float = DEFAULT_ELEVATED_RATIO,
    high_ratio: float = DEFAULT_HIGH_RATIO,
    critical_ratio: float = DEFAULT_CRITICAL_RATIO,
    capacity_rate_r: float = 2.0
) -> pd.DataFrame:
    """
    Merges 30-minute demand forecasts with simulated supply across (origin, h3_cell),
    and computes pressure metrics.
    """
    # Merge on (origin, h3_cell)
    merged = pd.merge(
        forecasts_df,
        supply_df[["origin", "h3_cell", "available_vehicles_V", "capacity_rate_r", "estimated_capacity_C", "supply_data_status", "simulation_run_id"]],
        on=["origin", "h3_cell"],
        how="outer"
    )

    records = []
    for _, row in merged.iterrows():
        d_val = row.get("predicted_rides")
        v_val = row.get("available_vehicles_V")
        r_val = row.get("capacity_rate_r", capacity_rate_r)
        
        # Determine input status
        if pd.isna(d_val) or pd.isna(v_val):
            in_status = INPUT_STATUS_MISSING
        else:
            in_status = INPUT_STATUS_OK

        res = evaluate_single_pressure_record(
            demand_d=d_val,
            vehicles_v=int(v_val) if pd.notna(v_val) else None,
            capacity_rate_r=float(r_val) if pd.notna(r_val) else capacity_rate_r,
            elevated_ratio=elevated_ratio,
            high_ratio=high_ratio,
            critical_ratio=critical_ratio,
            input_status=in_status
        )

        records.append({
            "h3_cell": row["h3_cell"],
            "as_of": row["origin"],
            "forecast_origin": row["origin"],
            "target_start": row.get("target_start"),
            "target_end": row.get("target_end"),
            "model_name": row.get("model_name", "xgboost"),
            "capacity_rate_r": float(r_val) if pd.notna(r_val) else capacity_rate_r,
            "forecast_demand_rides_30m": res["predicted_rides_D"],
            "predicted_rides_D": res["predicted_rides_D"],
            "simulated_available_vehicles": res["available_vehicles_V"],
            "available_vehicles_V": res["available_vehicles_V"],
            "estimated_supply_capacity_rides_30m": res["estimated_capacity_C"],
            "estimated_capacity_C": res["estimated_capacity_C"],
            "demand_supply_ratio": res["demand_supply_ratio"],
            "pressure_index": res["pressure_index"],
            "estimated_unserved_demand_rides": res["estimated_unserved_demand_rides"],
            "pressure_status": res["pressure_status"],
            "pressure_level": res["pressure_level"],
            "input_status": res["input_status"],
            "supply_data_status": SUPPLY_DATA_STATUS,
            "simulation_run_id": row.get("simulation_run_id", "sim-default")
        })

    return pd.DataFrame(records)

