"""
RideIntel Phase 4 Pipeline Execution Job.

Orchestrates:
1. Loading Phase 3 30-minute demand forecasts.
2. Simulating causal, time-varying supply capacity across 135 operational zones.
3. Calculating demand-supply pressure ratios and unserved demand.
4. Detecting potential demand surges.
5. Persisting zone_pressure_status.parquet and surge_alerts.parquet.
6. Generating machine-readable audit evidence.
"""

import os
import sys
import json
import uuid
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from pipeline.simulation.supply import (
    SupplySimulator,
    DEFAULT_FLEET_SIZE,
    DEFAULT_AVAILABILITY_RATIO,
    DEFAULT_CAPACITY_RATE,
    DEFAULT_SEED
)
from pipeline.simulation.pressure import (
    compute_demand_supply_pressure_table,
    DEFAULT_ELEVATED_RATIO,
    DEFAULT_HIGH_RATIO,
    DEFAULT_CRITICAL_RATIO
)
from pipeline.simulation.surge import (
    detect_potential_surges,
    DEFAULT_MIN_SURGE_DEMAND,
    DEFAULT_SURGE_RATIO_THRESHOLD,
    DEFAULT_GROWTH_THRESHOLD
)

logger = logging.getLogger("rideintel.simulation")

DEFAULT_SETTINGS_PATH = "settings.yaml"
DEFAULT_FORECASTS_PARQUET = os.path.join("data", "processed", "forecasts", "forecasts.parquet")
DEFAULT_OUTPUT_DIR = os.path.join("data", "processed", "simulation")
DEFAULT_EVIDENCE_DIR = os.path.join("docs", "evidence")


def load_settings(settings_path: str = DEFAULT_SETTINGS_PATH) -> Dict[str, Any]:
    """Loads configuration settings from YAML."""
    if not os.path.exists(settings_path):
        return {}
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_simulation_pipeline(
    forecasts_parquet: str = DEFAULT_FORECASTS_PARQUET,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    evidence_dir: str = DEFAULT_EVIDENCE_DIR,
    settings_path: str = DEFAULT_SETTINGS_PATH,
    simulation_run_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the full Phase 4 supply simulation and pressure detection pipeline.
    """
    run_id = simulation_run_id or f"sim-{uuid.uuid4().hex[:8]}"
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)

    logger.info(f"=== Starting RideIntel Phase 4 Pipeline (Run ID: {run_id}) ===")

    # 1. Load configuration
    cfg = load_settings(settings_path)
    sim_cfg = cfg.get("simulation", {})
    cap_cfg = cfg.get("capacity", {})
    press_cfg = cfg.get("pressure", {})
    surge_cfg = cfg.get("surge", {})

    random_seed = int(sim_cfg.get("random_seed", DEFAULT_SEED))
    fleet_size = int(sim_cfg.get("fleet_size", DEFAULT_FLEET_SIZE))
    avail_ratio = float(sim_cfg.get("availability_ratio", DEFAULT_AVAILABILITY_RATIO))
    capacity_rate_r = float(cap_cfg.get("rate_r", DEFAULT_CAPACITY_RATE))

    elevated_ratio = float(press_cfg.get("elevated_ratio", DEFAULT_ELEVATED_RATIO))
    high_ratio = float(press_cfg.get("high_ratio", DEFAULT_HIGH_RATIO))
    critical_ratio = float(press_cfg.get("critical_ratio", DEFAULT_CRITICAL_RATIO))

    min_surge_demand = float(surge_cfg.get("min_surge_demand", DEFAULT_MIN_SURGE_DEMAND))
    surge_ratio_thresh = float(surge_cfg.get("surge_ratio_threshold", DEFAULT_SURGE_RATIO_THRESHOLD))
    growth_thresh = float(surge_cfg.get("growth_threshold", DEFAULT_GROWTH_THRESHOLD))

    logger.info(
        f"Configuration: Fleet={fleet_size}, Rate={capacity_rate_r}, Seed={random_seed}, "
        f"PressureThresholds=({elevated_ratio}, {high_ratio}, {critical_ratio})"
    )

    # 2. Read forecasts table
    if not os.path.exists(forecasts_parquet):
        raise FileNotFoundError(f"Forecasts table not found at: {forecasts_parquet}")

    fc_table = pq.read_table(forecasts_parquet)
    fc_df = fc_table.to_pandas()

    # Filter to primary XGBoost model forecasts
    xgb_df = fc_df[fc_df["model_name"] == "xgboost"].copy()
    xgb_df = xgb_df.rename(columns={"forecast_origin": "origin"})
    logger.info(f"Loaded {len(xgb_df):,} XGBoost forecast rows across {xgb_df['h3_cell'].nunique()} zones.")

    # Also extract rolling baseline as baseline demand
    baseline_df = fc_df[fc_df["model_name"] == "baseline_rolling_avg"].copy()
    baseline_df = baseline_df.rename(columns={"forecast_origin": "origin", "predicted_rides": "baseline_demand"})
    
    # Merge baseline demand into forecast DataFrame
    merged_fc = pd.merge(
        xgb_df,
        baseline_df[["origin", "h3_cell", "baseline_demand"]],
        on=["origin", "h3_cell"],
        how="left"
    )

    eligible_zones = sorted(xgb_df["h3_cell"].unique().tolist())
    origins = sorted(xgb_df["origin"].unique().tolist())
    logger.info(f"Target grid: {len(origins)} origins, {len(eligible_zones)} zones.")

    # 3. Supply Simulation
    # Calculate historical zone weights from the forecast means to seed realistic driver distribution
    zone_weights = xgb_df.groupby("h3_cell")["predicted_rides"].mean().to_dict()

    logger.info("Simulating available vehicle supply across origins...")
    simulator = SupplySimulator(
        eligible_zones=eligible_zones,
        zone_historical_weights=zone_weights,
        fleet_size=fleet_size,
        base_availability_ratio=avail_ratio,
        capacity_rate_r=capacity_rate_r,
        random_seed=random_seed
    )

    supply_df = simulator.simulate_grid_supply(origins=origins, simulation_run_id=run_id)
    logger.info(f"Simulated {len(supply_df):,} zone-origin supply instances.")

    # 4. Compute Demand-Supply Pressure Table
    logger.info("Computing demand-supply pressure ratios and unserved demand...")
    pressure_df = compute_demand_supply_pressure_table(
        forecasts_df=merged_fc,
        supply_df=supply_df,
        elevated_ratio=elevated_ratio,
        high_ratio=high_ratio,
        critical_ratio=critical_ratio,
        capacity_rate_r=capacity_rate_r
    )

    # 5. Detect Potential Surges
    logger.info("Evaluating potential surge detection heuristics...")
    annotated_df, surge_alerts_df = detect_potential_surges(
        pressure_df=pressure_df,
        min_surge_demand=min_surge_demand,
        surge_ratio_threshold=surge_ratio_thresh,
        growth_threshold=growth_thresh
    )

    # 6. Save Parquet Outputs
    pressure_parquet_path = os.path.join(output_dir, "zone_pressure_status.parquet")
    pq.write_table(pa.Table.from_pandas(annotated_df), pressure_parquet_path, compression="snappy")
    logger.info(f"Saved zone pressure status table: {pressure_parquet_path} ({len(annotated_df):,} rows)")

    surge_parquet_path = os.path.join(output_dir, "surge_alerts.parquet")
    pq.write_table(pa.Table.from_pandas(surge_alerts_df), surge_parquet_path, compression="snappy")
    logger.info(f"Saved surge alerts table: {surge_parquet_path} ({len(surge_alerts_df):,} rows)")

    # 7. Summary & Metrics Generation
    pressure_counts = annotated_df["pressure_level"].value_counts().to_dict()
    status_counts = annotated_df["pressure_status"].value_counts().to_dict()
    surge_count = int(annotated_df["is_potential_surge"].sum())
    surge_severity_counts = annotated_df[annotated_df["is_potential_surge"]]["surge_severity"].value_counts().to_dict()

    total_unserved = float(annotated_df["estimated_unserved_demand_rides"].sum())

    summary_payload = {
        "simulation_run_id": run_id,
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "random_seed": random_seed,
            "fleet_size": fleet_size,
            "availability_ratio": avail_ratio,
            "capacity_rate_r": capacity_rate_r,
            "elevated_ratio": elevated_ratio,
            "high_ratio": high_ratio,
            "critical_ratio": critical_ratio,
            "min_surge_demand": min_surge_demand,
            "surge_ratio_threshold": surge_ratio_thresh,
            "growth_threshold": growth_thresh
        },
        "coverage": {
            "total_records": len(annotated_df),
            "unique_origins": len(origins),
            "unique_zones": len(eligible_zones),
            "origin_min": origins[0].isoformat(),
            "origin_max": origins[-1].isoformat(),
            "horizon_minutes": 30
        },
        "pressure_distribution": {
            "by_pressure_level": pressure_counts,
            "by_pressure_status": status_counts,
            "total_estimated_unserved_demand_rides": total_unserved
        },
        "surge_summary": {
            "total_potential_surges": surge_count,
            "surge_percentage": float(surge_count / len(annotated_df) * 100.0) if len(annotated_df) > 0 else 0.0,
            "by_severity": surge_severity_counts,
            "total_surge_alerts_persisted": len(surge_alerts_df)
        }
    }

    evidence_json_path = os.path.join(evidence_dir, "phase4_supply_pressure_summary.json")
    with open(evidence_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)
    logger.info(f"Saved summary evidence to: {evidence_json_path}")

    return summary_payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_simulation_pipeline()

