"""
RideIntel Artifact Service.

Loads, validates, filters, and caches Parquet and JSON artifacts.
Ensures zero NaN/infinity leaks, strict parameter validation, and robust error handling.
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
import math
import json
from pathlib import Path
import pandas as pd
import numpy as np

from api.config import APIConfig, config as default_config
from api.schemas import (
    ComponentHealth,
    HealthResponse,
    MetadataResponse,
    MetricsResponse,
    ModelMetricItem
)


class ArtifactUnavailableError(Exception):
    """Raised when an essential artifact cannot be read or found."""
    pass


class ResourceNotFoundError(Exception):
    """Raised when a specific requested resource (e.g., zone) does not exist."""
    pass


class InvalidParameterError(Exception):
    """Raised when query parameters fail domain validation."""
    pass


def clean_val(v: Any) -> Any:
    """Replaces NaN, Infinity, and NaT with None."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if pd.isna(v):
        return None
    return v


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures datetime is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ArtifactService:
    """
    Cached service providing access to all Phase 1-4 project artifacts.
    """

    def __init__(self, cfg: Optional[APIConfig] = None):
        self.cfg = cfg or default_config
        self._forecasts_df: Optional[pd.DataFrame] = None
        self._pressure_df: Optional[pd.DataFrame] = None
        self._surge_alerts_df: Optional[pd.DataFrame] = None
        self._zone_universe_df: Optional[pd.DataFrame] = None
        self._evaluation_summary: Optional[Dict[str, Any]] = None
        self._known_zones: Optional[set] = None

    def clear_cache(self):
        """Clears cached datasets to force reloading."""
        self._forecasts_df = None
        self._pressure_df = None
        self._surge_alerts_df = None
        self._zone_universe_df = None
        self._evaluation_summary = None
        self._known_zones = None

    # --------------------------------------------------------------------------
    # Cache Loaders
    # --------------------------------------------------------------------------

    def get_zone_universe(self) -> pd.DataFrame:
        if self._zone_universe_df is None:
            p = self.cfg.zone_universe_path
            if not p.exists():
                raise ArtifactUnavailableError(f"Zone universe artifact missing at: {p.name}")
            try:
                self._zone_universe_df = pd.read_parquet(p)
                self._known_zones = set(self._zone_universe_df["h3_cell"].unique())
            except Exception as e:
                raise ArtifactUnavailableError(f"Failed to read zone universe: {e}")
        return self._zone_universe_df

    def get_known_zones(self) -> set:
        if self._known_zones is None:
            self.get_zone_universe()
        return self._known_zones

    def get_forecasts_table(self) -> pd.DataFrame:
        if self._forecasts_df is None:
            p = self.cfg.forecasts_path
            if not p.exists():
                raise ArtifactUnavailableError(f"Forecasts artifact missing at: {p.name}")
            try:
                df = pd.read_parquet(p)
                # Ensure UTC datetime
                if not isinstance(df["forecast_origin"].dtype, pd.DatetimeTZDtype):
                    df["forecast_origin"] = pd.to_datetime(df["forecast_origin"], utc=True)
                self._forecasts_df = df
            except Exception as e:
                raise ArtifactUnavailableError(f"Failed to read forecasts table: {e}")
        return self._forecasts_df

    def get_pressure_table(self) -> pd.DataFrame:
        if self._pressure_df is None:
            p = self.cfg.pressure_path
            if not p.exists():
                raise ArtifactUnavailableError(f"Pressure status artifact missing at: {p.name}")
            try:
                df = pd.read_parquet(p)
                if not isinstance(df["forecast_origin"].dtype, pd.DatetimeTZDtype):
                    df["forecast_origin"] = pd.to_datetime(df["forecast_origin"], utc=True)
                self._pressure_df = df
            except Exception as e:
                raise ArtifactUnavailableError(f"Failed to read pressure table: {e}")
        return self._pressure_df

    def get_surge_alerts_table(self) -> pd.DataFrame:
        if self._surge_alerts_df is None:
            p = self.cfg.surge_alerts_path
            if not p.exists():
                raise ArtifactUnavailableError(f"Surge alerts artifact missing at: {p.name}")
            try:
                df = pd.read_parquet(p)
                if not isinstance(df["forecast_origin"].dtype, pd.DatetimeTZDtype):
                    df["forecast_origin"] = pd.to_datetime(df["forecast_origin"], utc=True)
                self._surge_alerts_df = df
            except Exception as e:
                raise ArtifactUnavailableError(f"Failed to read surge alerts table: {e}")
        return self._surge_alerts_df

    def get_evaluation_summary(self) -> Dict[str, Any]:
        if self._evaluation_summary is None:
            p = self.cfg.evaluation_summary_path
            if not p.exists():
                raise ArtifactUnavailableError(f"Forecasting evaluation summary missing at: {p.name}")
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self._evaluation_summary = json.load(f)
            except Exception as e:
                raise ArtifactUnavailableError(f"Failed to read evaluation summary: {e}")
        return self._evaluation_summary

    # --------------------------------------------------------------------------
    # Health & Metadata
    # --------------------------------------------------------------------------

    def check_health(self) -> HealthResponse:
        components: List[ComponentHealth] = []
        is_healthy = True

        # Check Zone Universe
        try:
            zu_df = self.get_zone_universe()
            components.append(ComponentHealth(
                name="zone_universe",
                status="HEALTHY",
                path=self.cfg.zone_universe_path.name,
                records=len(zu_df),
                detail=f"{zu_df['is_operational_universe'].sum()} operational zones out of {len(zu_df)}"
            ))
        except Exception as e:
            is_healthy = False
            components.append(ComponentHealth(
                name="zone_universe",
                status="UNAVAILABLE",
                path=self.cfg.zone_universe_path.name,
                detail=str(e)
            ))

        # Check Forecasts
        try:
            fc_df = self.get_forecasts_table()
            components.append(ComponentHealth(
                name="forecast_store",
                status="HEALTHY",
                path=self.cfg.forecasts_path.name,
                records=len(fc_df),
                detail=f"Models: {list(fc_df['model_name'].unique())}"
            ))
        except Exception as e:
            is_healthy = False
            components.append(ComponentHealth(
                name="forecast_store",
                status="UNAVAILABLE",
                path=self.cfg.forecasts_path.name,
                detail=str(e)
            ))

        # Check Pressure
        try:
            pr_df = self.get_pressure_table()
            components.append(ComponentHealth(
                name="pressure_store",
                status="HEALTHY",
                path=self.cfg.pressure_path.name,
                records=len(pr_df),
                detail=f"Pressure levels: {list(pr_df['pressure_level'].unique())}"
            ))
        except Exception as e:
            is_healthy = False
            components.append(ComponentHealth(
                name="pressure_store",
                status="UNAVAILABLE",
                path=self.cfg.pressure_path.name,
                detail=str(e)
            ))

        # Check Surge Alerts
        try:
            sg_df = self.get_surge_alerts_table()
            components.append(ComponentHealth(
                name="surge_store",
                status="HEALTHY",
                path=self.cfg.surge_alerts_path.name,
                records=len(sg_df),
                detail=f"{len(sg_df)} surge alerts persisted"
            ))
        except Exception as e:
            is_healthy = False
            components.append(ComponentHealth(
                name="surge_store",
                status="UNAVAILABLE",
                path=self.cfg.surge_alerts_path.name,
                detail=str(e)
            ))

        # Check Evaluation Summary
        try:
            ev_summary = self.get_evaluation_summary()
            components.append(ComponentHealth(
                name="metrics_summary",
                status="HEALTHY",
                path=self.cfg.evaluation_summary_path.name,
                records=len(ev_summary.get("overall_evaluation", {})),
                detail="Held-out test metrics available"
            ))
        except Exception as e:
            is_healthy = False
            components.append(ComponentHealth(
                name="metrics_summary",
                status="UNAVAILABLE",
                path=self.cfg.evaluation_summary_path.name,
                detail=str(e)
            ))

        overall_status = "HEALTHY" if is_healthy else "UNHEALTHY"
        return HealthResponse(
            status=overall_status,
            timestamp=datetime.now(timezone.utc),
            components=components
        )

    def get_metadata(self) -> MetadataResponse:
        zu_df = self.get_zone_universe()
        fc_df = self.get_forecasts_table()

        retrospective_count = int(zu_df["is_operational_universe"].sum())
        total_catalog = len(zu_df)
        forecast_eligible_count = int(fc_df["h3_cell"].nunique())
        available_models = sorted(fc_df["model_name"].unique().tolist())

        return MetadataResponse(
            dataset_period="2022-06-01T05:00:00Z to 2022-07-01T05:00:00Z",
            split_boundary_utc="2022-06-22T05:00:00Z",
            storage_timezone="UTC",
            display_timezone=self.cfg.settings.get("display", {}).get("timezone", "America/Chicago"),
            forecast_eligible_zones=forecast_eligible_count,
            operational_zone_count=forecast_eligible_count,
            retrospective_operational_zones=retrospective_count,
            total_catalog_zones=total_catalog,
            h3_resolution=int(self.cfg.settings.get("h3", {}).get("resolution", 8)),
            window_minutes=int(self.cfg.settings.get("window_minutes", 15)),
            forecast_horizon_minutes=int(self.cfg.settings.get("horizon_minutes", 30)),
            available_models=available_models,
            default_model="xgboost",
            source_labels={
                "observed_demand": "HISTORICAL",
                "predicted_rides": "PREDICTED",
                "available_vehicles": "SIMULATED",
                "estimated_capacity": "SIMULATED_ESTIMATE",
                "demand_supply_pressure": "ESTIMATED"
            },
            streaming_status="OFFLINE_PROTOTYPE (Host Docker/WSL2 unavailable; live Kafka broker tests skipped)",
            supply_data_status="SIMULATED_ESTIMATE (Synthetic driver supply simulation seeded per origin)",
            disclaimer=(
                "All vehicle counts and supply capacity values are SIMULATED decision-support estimates. "
                "No live fleet tracking or real-world driver inventory is present in the historical Chicago taxi dataset."
            )
        )

    # --------------------------------------------------------------------------
    # Forecasts Filtering & Pagination
    # --------------------------------------------------------------------------

    def get_forecasts(
        self,
        model: str = "xgboost",
        zone: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[int, List[Dict[str, Any]]]:
        df = self.get_forecasts_table()
        available_models = df["model_name"].unique()
        if model not in available_models:
            raise InvalidParameterError(
                f"Model '{model}' not recognized. Available models: {sorted(available_models)}"
            )

        # Validate zone if requested
        if zone:
            known = self.get_known_zones()
            if zone not in known:
                raise ResourceNotFoundError(f"Zone '{zone}' not found in zone universe.")

        # Time range validation
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if start_utc and end_utc and start_utc > end_utc:
            raise InvalidParameterError(
                f"Start timestamp ({start_utc.isoformat()}) must be before or equal to end timestamp ({end_utc.isoformat()})."
            )

        # Apply filtering
        mask = (df["model_name"] == model)
        if zone:
            mask = mask & (df["h3_cell"] == zone)
        if start_utc:
            mask = mask & (df["forecast_origin"] >= start_utc)
        if end_utc:
            mask = mask & (df["forecast_origin"] <= end_utc)

        filtered = df[mask].sort_values(by=["forecast_origin", "h3_cell"])
        total_records = len(filtered)

        # Paginate
        page = filtered.iloc[offset : offset + limit]

        records: List[Dict[str, Any]] = []
        for _, row in page.iterrows():
            records.append({
                "forecast_id": str(row["forecast_id"]),
                "h3_cell": str(row["h3_cell"]),
                "forecast_origin": row["forecast_origin"].to_pydatetime(),
                "target_start": row["target_start"].to_pydatetime(),
                "target_end": row["target_end"].to_pydatetime(),
                "predicted_rides": clean_val(row["predicted_rides"]),
                "model_name": str(row["model_name"]),
                "model_version": str(row.get("model_version", "v1.0.0")),
                "forecast_status": str(row.get("forecast_status", "CURRENT")),
                "source_type": "PREDICTED"
            })

        return total_records, records

    # --------------------------------------------------------------------------
    # Pressure Filtering & Pagination
    # --------------------------------------------------------------------------

    def get_pressure(
        self,
        zone: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        pressure_level: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[int, List[Dict[str, Any]]]:
        df = self.get_pressure_table()

        if zone:
            known = self.get_known_zones()
            if zone not in known:
                raise ResourceNotFoundError(f"Zone '{zone}' not found in zone universe.")

        if pressure_level:
            valid_levels = {"LOW", "MODERATE", "HIGH", "CRITICAL", "NO_CAPACITY"}
            if pressure_level.upper() not in valid_levels:
                raise InvalidParameterError(
                    f"Invalid pressure_level '{pressure_level}'. Valid options: {sorted(valid_levels)}"
                )

        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if start_utc and end_utc and start_utc > end_utc:
            raise InvalidParameterError(
                f"Start timestamp ({start_utc.isoformat()}) must be before or equal to end timestamp ({end_utc.isoformat()})."
            )

        mask = pd.Series(True, index=df.index)
        if zone:
            mask = mask & (df["h3_cell"] == zone)
        if start_utc:
            mask = mask & (df["forecast_origin"] >= start_utc)
        if end_utc:
            mask = mask & (df["forecast_origin"] <= end_utc)
        if pressure_level:
            mask = mask & (df["pressure_level"] == pressure_level.upper())

        filtered = df[mask].sort_values(by=["forecast_origin", "h3_cell"])
        total_records = len(filtered)

        page = filtered.iloc[offset : offset + limit]

        records: List[Dict[str, Any]] = []
        for _, row in page.iterrows():
            records.append({
                "h3_cell": str(row["h3_cell"]),
                "forecast_origin": row["forecast_origin"].to_pydatetime(),
                "target_start": row["target_start"].to_pydatetime(),
                "target_end": row["target_end"].to_pydatetime(),
                "model_name": str(row.get("model_name", "xgboost")),
                "capacity_rate_r": clean_val(row.get("capacity_rate_r", 2.0)),
                "forecast_demand_rides_30m": clean_val(row.get("forecast_demand_rides_30m", row.get("predicted_rides_D"))),
                "predicted_rides_D": clean_val(row.get("predicted_rides_D")),
                "simulated_available_vehicles": int(row.get("simulated_available_vehicles", 0)),
                "available_vehicles_V": int(row.get("available_vehicles_V", 0)),
                "estimated_supply_capacity_rides_30m": clean_val(row.get("estimated_supply_capacity_rides_30m")),
                "estimated_capacity_C": clean_val(row.get("estimated_capacity_C")),
                "demand_supply_ratio": clean_val(row.get("demand_supply_ratio")),
                "pressure_index": clean_val(row.get("pressure_index")),
                "estimated_unserved_demand_rides": clean_val(row.get("estimated_unserved_demand_rides", 0.0)),
                "pressure_status": str(row.get("pressure_status", "NORMAL")),
                "pressure_level": str(row.get("pressure_level", "LOW")),
                "input_status": str(row.get("input_status", "OK")),
                "supply_data_status": str(row.get("supply_data_status", "SIMULATED_ESTIMATE")),
                "is_potential_surge": bool(row.get("is_potential_surge", False)),
                "surge_severity": str(row.get("surge_severity", "NONE")),
                "source_type": "ESTIMATED"
            })

        return total_records, records

    # --------------------------------------------------------------------------
    # Surge Alerts Filtering & Pagination
    # --------------------------------------------------------------------------

    def get_surge_alerts(
        self,
        zone: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        severity: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[int, List[Dict[str, Any]]]:
        df = self.get_surge_alerts_table()

        if zone:
            known = self.get_known_zones()
            if zone not in known:
                raise ResourceNotFoundError(f"Zone '{zone}' not found in zone universe.")

        if severity:
            valid_severities = {"HIGH", "CRITICAL"}
            if severity.upper() not in valid_severities:
                raise InvalidParameterError(
                    f"Invalid severity '{severity}'. Valid options: {sorted(valid_severities)}"
                )

        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if start_utc and end_utc and start_utc > end_utc:
            raise InvalidParameterError(
                f"Start timestamp ({start_utc.isoformat()}) must be before or equal to end timestamp ({end_utc.isoformat()})."
            )

        mask = pd.Series(True, index=df.index)
        if zone:
            mask = mask & (df["h3_cell"] == zone)
        if start_utc:
            mask = mask & (df["forecast_origin"] >= start_utc)
        if end_utc:
            mask = mask & (df["forecast_origin"] <= end_utc)
        if severity:
            mask = mask & (df["severity"] == severity.upper())

        filtered = df[mask].sort_values(by=["forecast_origin", "h3_cell"])
        total_records = len(filtered)

        page = filtered.iloc[offset : offset + limit]

        records: List[Dict[str, Any]] = []
        for _, row in page.iterrows():
            records.append({
                "alert_id": str(row["alert_id"]),
                "h3_cell": str(row["h3_cell"]),
                "detected_at": row["detected_at"].to_pydatetime(),
                "forecast_origin": row["forecast_origin"].to_pydatetime(),
                "observed_demand": int(row["observed_demand"]),
                "predicted_demand": clean_val(row["predicted_demand"]),
                "baseline_demand": clean_val(row["baseline_demand"]),
                "severity": str(row["severity"]),
                "simulation_run_id": str(row.get("simulation_run_id", "sim-default")),
                "source_type": "SIMULATED_ESTIMATE"
            })

        return total_records, records

    # --------------------------------------------------------------------------
    # Evaluation Metrics
    # --------------------------------------------------------------------------

    def get_metrics(self, model: Optional[str] = None) -> MetricsResponse:
        summary = self.get_evaluation_summary()
        overall = summary.get("overall_evaluation", {})

        if model:
            if model not in overall:
                raise InvalidParameterError(
                    f"Model '{model}' not found in evaluation metrics. Available models: {sorted(overall.keys())}"
                )
            overall = {model: overall[model]}

        metrics_items: Dict[str, ModelMetricItem] = {}
        for m_name, m_data in overall.items():
            metrics_items[m_name] = ModelMetricItem(
                model_name=m_name,
                model_version="v1.0.0",
                count=int(m_data["count"]),
                sum_actual=float(m_data["sum_actual"]),
                mae=float(m_data["mae"]),
                rmse=float(m_data["rmse"]),
                wape=clean_val(m_data.get("wape")),
                wape_status=str(m_data.get("wape_status", "VALID"))
            )

        temporal = summary.get("temporal_parameters", {})
        test_interval = {
            "start": temporal.get("test_start_utc", "2022-06-22T05:00:00Z"),
            "end": temporal.get("dataset_end_utc", "2022-07-01T05:00:00Z"),
            "total_test_days": 9
        }

        return MetricsResponse(
            evaluation_type="HELD_OUT_TEST_SET",
            test_interval=test_interval,
            test_rows_per_model=int(summary.get("dataset_sample_counts", {}).get("test_target_rows_per_model", 116505)),
            overall_metrics=metrics_items,
            density_group_breakdown=summary.get("density_group_breakdown"),
            hourly_breakdown=summary.get("hourly_breakdown"),
            notes=(
                "All models were evaluated on the identical set of 116,505 held-out test rows "
                "(863 prediction origins x 135 operational zones). "
                "Metrics are strictly historical and never recomputed or fabricated at runtime."
            )
        )


# Global default service instance
service = ArtifactService()
