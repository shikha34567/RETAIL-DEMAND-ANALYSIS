"""
RideIntel Potential Demand Surge Detection Module.

Applies configurable, transparent heuristics to detect potential demand surges
where predicted 30-minute demand exceeds supply capacity and baseline expectations.

NOTE: These flags represent prototype decision-support heuristics,
not real-world dynamic pricing surge probabilities.
"""

import uuid
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
import numpy as np

DEFAULT_MIN_SURGE_DEMAND = 5.0
DEFAULT_SURGE_RATIO_THRESHOLD = 1.2
DEFAULT_GROWTH_THRESHOLD = 1.3


def evaluate_surge_for_row(
    forecast_demand: Optional[float],
    capacity: Optional[float],
    pressure_ratio: Optional[float],
    baseline_demand: Optional[float] = None,
    min_surge_demand: float = DEFAULT_MIN_SURGE_DEMAND,
    surge_ratio_threshold: float = DEFAULT_SURGE_RATIO_THRESHOLD,
    growth_threshold: float = DEFAULT_GROWTH_THRESHOLD
) -> Dict[str, Any]:
    """
    Evaluates whether an observation triggers a potential surge alert.
    """
    if forecast_demand is None or pd.isna(forecast_demand):
        return {
            "is_potential_surge": False,
            "surge_severity": "NONE",
            "surge_trigger_reason": "MISSING_FORECAST"
        }

    d = float(forecast_demand)
    c = float(capacity) if (capacity is not None and not pd.isna(capacity)) else 0.0

    # Low demand zones do not trigger surge alerts (filters sporadic 1-2 ride spikes)
    if d < min_surge_demand:
        return {
            "is_potential_surge": False,
            "surge_severity": "NONE",
            "surge_trigger_reason": "DEMAND_BELOW_MINIMUM_THRESHOLD"
        }

    # Case A: Zero capacity with substantial demand (C = 0, D >= min_surge_demand)
    if c == 0.0 and d >= min_surge_demand:
        severity = "CRITICAL" if d >= 10.0 else "HIGH"
        return {
            "is_potential_surge": True,
            "surge_severity": severity,
            "surge_trigger_reason": "ZERO_CAPACITY_UNSERVED_DEMAND"
        }

    # Case B: Capacity > 0, evaluate ratio
    ratio = pressure_ratio if (pressure_ratio is not None and not pd.isna(pressure_ratio)) else (d / c if c > 0 else 0.0)

    # Check baseline demand growth if baseline is available and stable (> 0)
    growth_condition_met = True
    if baseline_demand is not None and not pd.isna(baseline_demand) and baseline_demand >= 2.0:
        growth_condition_met = (d / float(baseline_demand)) >= growth_threshold

    if ratio >= surge_ratio_threshold and growth_condition_met:
        if ratio >= 1.5 or d >= 25.0:
            severity = "CRITICAL"
        else:
            severity = "HIGH"

        return {
            "is_potential_surge": True,
            "surge_severity": severity,
            "surge_trigger_reason": f"RATIO_EXCEEDS_THRESHOLD ({ratio:.2f} >= {surge_ratio_threshold})"
        }

    return {
        "is_potential_surge": False,
        "surge_severity": "NONE",
        "surge_trigger_reason": "CONDITIONS_NOT_MET"
    }


def detect_potential_surges(
    pressure_df: pd.DataFrame,
    min_surge_demand: float = DEFAULT_MIN_SURGE_DEMAND,
    surge_ratio_threshold: float = DEFAULT_SURGE_RATIO_THRESHOLD,
    growth_threshold: float = DEFAULT_GROWTH_THRESHOLD
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Applies surge detection heuristics across the pressure DataFrame.

    Returns:
      - annotated_df: input DataFrame with 'is_potential_surge' and 'surge_severity' columns.
      - surge_alerts_df: table conforming to contracts/parquet_schemas.md (Table 7: surge_alerts).
    """
    is_surge_list = []
    severity_list = []
    reason_list = []
    alerts = []

    for _, row in pressure_df.iterrows():
        d = row.get("forecast_demand_rides_30m")
        c = row.get("estimated_supply_capacity_rides_30m")
        p = row.get("demand_supply_ratio")
        b = row.get("baseline_demand")

        res = evaluate_surge_for_row(
            forecast_demand=d,
            capacity=c,
            pressure_ratio=p,
            baseline_demand=b,
            min_surge_demand=min_surge_demand,
            surge_ratio_threshold=surge_ratio_threshold,
            growth_threshold=growth_threshold
        )

        is_surge_list.append(res["is_potential_surge"])
        severity_list.append(res["surge_severity"])
        reason_list.append(res["surge_trigger_reason"])

        if res["is_potential_surge"]:
            alert_id = f"alert-{uuid.uuid4().hex[:12]}"
            alerts.append({
                "alert_id": alert_id,
                "h3_cell": row["h3_cell"],
                "detected_at": row["as_of"],
                "forecast_origin": row["as_of"],
                "observed_demand": int(np.round(d)) if pd.notna(d) else 0,
                "predicted_demand": float(d) if pd.notna(d) else 0.0,
                "baseline_demand": float(b) if (b is not None and pd.notna(b)) else None,
                "severity": res["surge_severity"],
                "simulation_run_id": row.get("simulation_run_id", "sim-default")
            })

    annotated_df = pressure_df.copy()
    annotated_df["is_potential_surge"] = is_surge_list
    annotated_df["surge_severity"] = severity_list
    annotated_df["surge_trigger_reason"] = reason_list

    surge_alerts_df = pd.DataFrame(alerts)
    return annotated_df, surge_alerts_df
