"""
Unit tests verifying that API requests never modify or mutate underlying artifacts.
"""

import hashlib
from pathlib import Path
from fastapi.testclient import TestClient
from api.main import app

def hash_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def test_api_read_only_immutability():
    """Hits all endpoints and asserts hashes of Phase 1-4 artifacts remain invariant."""
    target_files = [
        Path("data/processed/forecasts/forecasts.parquet"),
        Path("data/processed/simulation/zone_pressure_status.parquet"),
        Path("data/processed/simulation/surge_alerts.parquet"),
        Path("data/processed/zone_universe/zone_universe.parquet"),
        Path("docs/evidence/forecasting_evaluation_summary.json"),
        Path("docs/evidence/phase4_supply_pressure_summary.json")
    ]

    before_hashes = {p: hash_file(p) for p in target_files}

    client = TestClient(app)
    # Execute multiple queries across all endpoints
    client.get("/api/v1/health")
    client.get("/api/v1/metadata")
    client.get("/api/v1/forecasts?limit=50")
    client.get("/api/v1/forecasts?model=baseline_rolling_avg&limit=50")
    client.get("/api/v1/pressure?limit=50")
    client.get("/api/v1/pressure?pressure_level=CRITICAL")
    client.get("/api/v1/surge-alerts")
    client.get("/api/v1/metrics")

    after_hashes = {p: hash_file(p) for p in target_files}

    for p in target_files:
        assert before_hashes[p] == after_hashes[p], f"Artifact {p.name} was mutated by API calls!"

