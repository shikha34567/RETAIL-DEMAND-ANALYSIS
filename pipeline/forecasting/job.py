"""
RideIntel End-to-End Demand Forecasting Pipeline Job.

Orchestrates:
1. Training-window zone eligibility (135 operational zones).
2. 15-minute aggregation, completeness verification, and deterministic zero-filling.
3. 30-minute forward target generation.
4. Chronological splitting (Train, Val, Test).
5. Feature matrix generation with strict no-lookahead.
6. Baseline generation (previous-window and seasonal-naive).
7. XGBoost model fitting and validation.
8. Identical-row evaluation on test partition.
9. Parquet artifact persistence and evidence generation.
"""

import os
import sys
import json
import uuid
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from pipeline.forecasting import (
    DATASET_START_UTC,
    TRAIN_VAL_SPLIT_UTC,
    TRAIN_TEST_SPLIT_UTC,
    DATASET_END_UTC,
    WINDOW_MINUTES,
    HORIZON_MINUTES,
    MIN_HISTORICAL_TRIPS,
    TARGET_RESOLUTION
)
from pipeline.forecasting.eligibility import (
    derive_training_eligible_zones,
    identify_leaked_zones
)
from pipeline.forecasting.aggregation import (
    generate_window_grid,
    aggregate_observed_trips,
    create_zero_filled_demand_grid,
    compute_target_demand
)
from pipeline.forecasting.features import (
    build_full_feature_matrix,
    FEATURE_COLUMNS
)
from pipeline.forecasting.baselines import (
    PreviousWindowBaseline,
    SeasonalNaiveBaseline
)
from pipeline.forecasting.model import (
    DemandXGBoostModel,
    DEFAULT_MODEL_PARAMS
)
from pipeline.forecasting.evaluate import (
    compute_metrics,
    evaluate_models_on_identical_rows,
    compute_metrics_by_group
)

logger = logging.getLogger("rideintel.forecasting")


def run_forecasting_pipeline(
    cleaned_parquet_path: str = os.path.join("data", "interim", "cleaned_trips_2022-06", "cleaned_trips.parquet"),
    output_dir: str = os.path.join("data", "processed", "forecasts"),
    models_dir: str = "models",
    evidence_dir: str = os.path.join("docs", "evidence"),
    processing_run_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the full forecasting pipeline and saves all required artifacts.
    """
    run_id = processing_run_id or f"run-fc-{uuid.uuid4().hex[:8]}"
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)

    logger.info(f"=== Starting RideIntel Forecasting Pipeline (Run ID: {run_id}) ===")

    # 1. Derive training eligibility (leakage-safe)
    logger.info("Deriving training-window zone eligibility...")
    eligibility_info = derive_training_eligible_zones(
        parquet_path=cleaned_parquet_path,
        split_cutoff_utc=TRAIN_TEST_SPLIT_UTC,
        min_trips=MIN_HISTORICAL_TRIPS,
        resolution=TARGET_RESOLUTION
    )
    eligible_zones = eligibility_info["eligible_zones"]
    leaked_zones = identify_leaked_zones(set(eligible_zones))
    logger.info(f"Qualified {len(eligible_zones)} zones for training. Identified {len(leaked_zones)} leaked retrospective zones.")

    # 2. Aggregate observed trips & build zero-filled continuous grid
    logger.info("Aggregating observed trips into 15-minute tumbling windows...")
    observed_agg = aggregate_observed_trips(
        parquet_path=cleaned_parquet_path,
        resolution=TARGET_RESOLUTION,
        window_minutes=WINDOW_MINUTES,
        filter_eligible_zones=set(eligible_zones)
    )

    logger.info("Creating zero-filled complete demand grid across June 2022...")
    demand_grid = create_zero_filled_demand_grid(
        observed_agg=observed_agg,
        eligible_zones=eligible_zones,
        start_utc=DATASET_START_UTC,
        end_utc=DATASET_END_UTC,
        window_minutes=WINDOW_MINUTES
    )
    logger.info(f"Demand grid constructed: {len(demand_grid):,} rows.")

    # 3. Compute 30-minute forward target demand
    logger.info("Computing 30-minute forward target demands...")
    target_df = compute_target_demand(
        demand_grid=demand_grid,
        horizon_minutes=HORIZON_MINUTES,
        window_minutes=WINDOW_MINUTES
    )

    # 4. Partition time boundaries
    # Train starts after 7 days of history (June 8) so lag_7d is non-null
    train_start_utc = DATASET_START_UTC + timedelta(days=7)
    val_start_utc = TRAIN_VAL_SPLIT_UTC
    test_start_utc = TRAIN_TEST_SPLIT_UTC
    # Test ends at June 30 23:30 local = 2022-07-01 04:30 UTC
    test_end_utc = DATASET_END_UTC - timedelta(minutes=HORIZON_MINUTES)

    all_origins = sorted(target_df["origin"].unique())
    train_origins = [o for o in all_origins if train_start_utc <= o < val_start_utc]
    val_origins = [o for o in all_origins if val_start_utc <= o < test_start_utc]
    test_origins = [o for o in all_origins if test_start_utc <= o <= test_end_utc]

    logger.info(f"Origins: Train={len(train_origins)}, Val={len(val_origins)}, Test={len(test_origins)}")

    # 5. Fit static zone statistics on Train target only
    train_targets_subset = target_df[target_df["origin"].isin(train_origins)]
    zone_means = train_targets_subset.groupby("h3_cell")["target_rides_30m"].mean().to_dict()

    # 6. Extract feature matrices
    logger.info("Extracting feature matrices for Train, Val, and Test...")
    all_pipeline_origins = train_origins + val_origins + test_origins
    full_feature_matrix = build_full_feature_matrix(
        demand_grid=demand_grid,
        origins=all_pipeline_origins,
        eligible_zones=eligible_zones,
        zone_means=zone_means
    )

    # Merge target with feature matrix
    full_dataset = pd.merge(
        full_feature_matrix,
        target_df[["origin", "h3_cell", "target_start", "target_end", "target_rides_30m"]],
        on=["origin", "h3_cell"],
        how="inner"
    )

    train_data = full_dataset[full_dataset["origin"].isin(train_origins)].copy()
    val_data = full_dataset[full_dataset["origin"].isin(val_origins)].copy()
    test_data = full_dataset[full_dataset["origin"].isin(test_origins)].copy()

    logger.info(f"Sample counts: Train={len(train_data):,}, Val={len(val_data):,}, Test={len(test_data):,}")

    # 7. Model Training: XGBoost
    logger.info("Training XGBoost demand regressor...")
    xgb_model = DemandXGBoostModel(params=DEFAULT_MODEL_PARAMS)
    xgb_model.fit(
        X_train=train_data,
        y_train=train_data["target_rides_30m"],
        X_val=val_data,
        y_val=val_data["target_rides_30m"]
    )

    model_path = os.path.join(models_dir, "xgboost_demand_model.json")
    xgb_model.save_model(model_path, metadata={"run_id": run_id, "train_origins": len(train_origins)})
    logger.info(f"Model saved to: {model_path}")

    # 8. Predictions on Held-Out Test Set
    logger.info("Generating predictions across all models on Test set...")
    # Model 1: XGBoost
    test_data["pred_xgboost"] = xgb_model.predict(test_data)

    # Model 2: Previous-window baseline
    prev_baseline = PreviousWindowBaseline()
    test_data["pred_prev_baseline"] = prev_baseline.predict_from_features(test_data)

    # Model 3: Seasonal-naive baseline
    seasonal_baseline = SeasonalNaiveBaseline()
    test_data["pred_seasonal_baseline"] = seasonal_baseline.predict_from_features(test_data)

    # 9. Format Evaluation DataFrame
    eval_rows = []
    for _, row in test_data.iterrows():
        base_meta = {
            "origin": row["origin"],
            "h3_cell": row["h3_cell"],
            "target_start": row["target_start"],
            "target_end": row["target_end"],
            "actual_rides": int(row["target_rides_30m"]),
            "hour_of_day": int(row["hour_of_day"]),
            "split": "test"
        }
        # Row for XGBoost
        eval_rows.append({
            **base_meta,
            "model_name": "xgboost",
            "model_version": "v1.0.0",
            "predicted_rides": float(row["pred_xgboost"])
        })
        # Row for previous window baseline
        eval_rows.append({
            **base_meta,
            "model_name": "baseline_rolling_avg",
            "model_version": "v1.0.0",
            "predicted_rides": float(row["pred_prev_baseline"])
        })
        # Row for seasonal naive baseline
        eval_rows.append({
            **base_meta,
            "model_name": "baseline_same_time_last_week",
            "model_version": "v1.0.0",
            "predicted_rides": float(row["pred_seasonal_baseline"])
        })

    raw_eval_df = pd.DataFrame(eval_rows)

    # 10. Perform Identical-Row Evaluation
    models_to_eval = ["xgboost", "baseline_rolling_avg", "baseline_same_time_last_week"]
    identical_eval_df, eval_summary = evaluate_models_on_identical_rows(
        eval_df=raw_eval_df,
        model_names=models_to_eval
    )
    logger.info(f"Identical evaluation set size: {eval_summary['retained_identical_pairs']:,} (origin, zone) pairs.")

    # Categorize zones into density groups based on historical training volume
    zone_vol_series = pd.Series(zone_means)
    q80 = zone_vol_series.quantile(0.80)
    q40 = zone_vol_series.quantile(0.40)

    def assign_density_group(val):
        if val >= q80:
            return "HIGH_DENSITY"
        elif val >= q40:
            return "MEDIUM_DENSITY"
        else:
            return "LOW_DENSITY"

    zone_density_map = {z: assign_density_group(m) for z, m in zone_means.items()}
    identical_eval_df["zone_density_group"] = identical_eval_df["h3_cell"].map(zone_density_map).fillna("LOW_DENSITY")

    # Group breakdowns
    by_density_metrics = compute_metrics_by_group(identical_eval_df, "zone_density_group", models_to_eval)
    by_hour_metrics = compute_metrics_by_group(identical_eval_df, "hour_of_day", models_to_eval)

    # 11. Write Forecasts Parquet Table (contracts/parquet_schemas.md Table 3)
    forecasts_records = []
    for _, row in identical_eval_df.iterrows():
        f_id = f"fc-{uuid.uuid4().hex[:12]}"
        forecasts_records.append({
            "forecast_id": f_id,
            "h3_cell": str(row["h3_cell"]),
            "forecast_origin": row["origin"],
            "target_start": row["target_start"],
            "target_end": row["target_end"],
            "predicted_rides": float(row["predicted_rides"]),
            "model_name": str(row["model_name"]),
            "model_version": str(row["model_version"]),
            "forecast_status": "CURRENT",
            "processing_run_id": run_id
        })
    forecasts_df = pd.DataFrame(forecasts_records)

    forecasts_path = os.path.join(output_dir, "forecasts.parquet")
    forecasts_table = pa.Table.from_pandas(forecasts_df)
    pq.write_table(forecasts_table, forecasts_path, compression="snappy")
    logger.info(f"Saved forecasts table: {forecasts_path} ({len(forecasts_df):,} rows)")

    # 12. Write Forecast Evaluation Parquet Table (contracts/parquet_schemas.md Table 4)
    eval_table_records = []
    for _, row in identical_eval_df.iterrows():
        eval_table_records.append({
            "h3_cell": str(row["h3_cell"]),
            "forecast_origin": row["origin"],
            "target_start": row["target_start"],
            "target_end": row["target_end"],
            "model_name": str(row["model_name"]),
            "model_version": str(row["model_version"]),
            "predicted_rides": float(row["predicted_rides"]),
            "actual_rides": int(row["actual_rides"]),
            "split": "test"
        })
    eval_table_df = pd.DataFrame(eval_table_records)

    eval_parquet_path = os.path.join(output_dir, "forecast_evaluation.parquet")
    eval_table = pa.Table.from_pandas(eval_table_df)
    pq.write_table(eval_table, eval_parquet_path, compression="snappy")
    logger.info(f"Saved forecast evaluation table: {eval_parquet_path} ({len(eval_table_df):,} rows)")

    # 13. Compile and save JSON evidence
    evidence_payload = {
        "run_id": run_id,
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "temporal_parameters": {
            "dataset_start_utc": DATASET_START_UTC.isoformat(),
            "train_val_split_utc": TRAIN_VAL_SPLIT_UTC.isoformat(),
            "train_test_split_utc": TRAIN_TEST_SPLIT_UTC.isoformat(),
            "dataset_end_utc": DATASET_END_UTC.isoformat(),
            "window_minutes": WINDOW_MINUTES,
            "horizon_minutes": HORIZON_MINUTES
        },
        "zone_eligibility": {
            "total_observed_zones": eligibility_info["total_observed_zones"],
            "training_eligible_zones_count": len(eligible_zones),
            "leaked_retrospective_zones_count": len(leaked_zones),
            "leaked_retrospective_zones": leaked_zones
        },
        "dataset_sample_counts": {
            "train_rows": len(train_data),
            "val_rows": len(val_data),
            "test_rows": len(test_data),
            "retained_identical_test_pairs": eval_summary["retained_identical_pairs"]
        },
        "overall_evaluation": eval_summary["overall_metrics"],
        "density_group_breakdown": by_density_metrics.to_dict(orient="records"),
        "hourly_breakdown": by_hour_metrics.to_dict(orient="records")
    }

    evidence_json_path = os.path.join(evidence_dir, "forecasting_evaluation_summary.json")
    with open(evidence_json_path, "w", encoding="utf-8") as f:
        json.dump(evidence_payload, f, indent=2)
    logger.info(f"Saved evidence summary to: {evidence_json_path}")

    return evidence_payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_forecasting_pipeline()
