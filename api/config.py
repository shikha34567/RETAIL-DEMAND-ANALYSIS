"""
RideIntel Backend Configuration.

Resolves artifact paths, settings, and CORS origins.
Supports environment variable overrides for testing and deployment.
"""

from pathlib import Path
import os
from typing import List
import yaml

# Base directory is repository root (parent of api/)
BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_path(rel_or_abs: str) -> Path:
    """Resolves a path relative to BASE_DIR if not already absolute."""
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()


class APIConfig:
    """Application configuration container."""

    def __init__(self):
        # Settings file
        self.settings_path = resolve_path(os.getenv("RIDEINTEL_SETTINGS_PATH", "settings.yaml"))
        
        # Artifact paths
        self.forecasts_path = resolve_path(
            os.getenv("RIDEINTEL_FORECASTS_PATH", "data/processed/forecasts/forecasts.parquet")
        )
        self.forecast_evaluation_path = resolve_path(
            os.getenv("RIDEINTEL_FORECAST_EVALUATION_PATH", "data/processed/forecasts/forecast_evaluation.parquet")
        )
        self.pressure_path = resolve_path(
            os.getenv("RIDEINTEL_PRESSURE_PATH", "data/processed/simulation/zone_pressure_status.parquet")
        )
        self.surge_alerts_path = resolve_path(
            os.getenv("RIDEINTEL_SURGE_ALERTS_PATH", "data/processed/simulation/surge_alerts.parquet")
        )
        self.zone_universe_path = resolve_path(
            os.getenv("RIDEINTEL_ZONE_UNIVERSE_PATH", "data/processed/zone_universe/zone_universe.parquet")
        )
        self.evaluation_summary_path = resolve_path(
            os.getenv("RIDEINTEL_EVALUATION_SUMMARY_PATH", "docs/evidence/forecasting_evaluation_summary.json")
        )
        self.simulation_summary_path = resolve_path(
            os.getenv("RIDEINTEL_SIMULATION_SUMMARY_PATH", "docs/evidence/phase4_supply_pressure_summary.json")
        )

        # CORS origins (Restricted for development, defaults to React dev server)
        default_origins = "http://localhost:5173,http://127.0.0.1:5173"
        cors_raw = os.getenv("RIDEINTEL_CORS_ORIGINS", default_origins)
        self.cors_origins: List[str] = [orig.strip() for orig in cors_raw.split(",") if orig.strip()]

        # Load settings if present
        self.settings = {}
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    self.settings = yaml.safe_load(f) or {}
            except Exception:
                self.settings = {}


# Global configuration instance
config = APIConfig()

