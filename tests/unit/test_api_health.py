"""
Unit tests for RideIntel Health & Metadata API endpoints.

Endpoints tested:
  - GET /api/v1/health
  - GET /api/v1/metadata
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_artifact_service
from api.config import APIConfig
from api.services.artifact_service import ArtifactService


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint_success(client):
    """Verifies GET /api/v1/health returns 200 and healthy component statuses."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "HEALTHY"
    assert "timestamp" in payload
    assert len(payload["components"]) >= 5

    names = {c["name"] for c in payload["components"]}
    expected_components = {"zone_universe", "forecast_store", "pressure_store", "surge_store", "metrics_summary"}
    assert expected_components.issubset(names)

    for comp in payload["components"]:
        assert comp["status"] == "HEALTHY"
        assert comp["records"] is not None
        assert comp["records"] > 0


def test_health_endpoint_missing_artifact_returns_503(client, tmp_path):
    """Verifies that when a critical artifact is missing, /api/v1/health returns 503."""
    # Create isolated config pointing to empty directory
    missing_cfg = APIConfig()
    missing_cfg.forecasts_path = tmp_path / "nonexistent_forecasts.parquet"
    test_svc = ArtifactService(cfg=missing_cfg)

    app.dependency_overrides[get_artifact_service] = lambda: test_svc
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "UNHEALTHY"
        
        # Verify component reflects unavailable status
        fc_comp = next((c for c in payload["components"] if c["name"] == "forecast_store"), None)
        assert fc_comp is not None
        assert fc_comp["status"] == "UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()


def test_metadata_endpoint_fields(client):
    """Verifies GET /api/v1/metadata returns complete metadata specifications."""
    response = client.get("/api/v1/metadata")
    assert response.status_code == 200
    data = response.json()

    assert data["storage_timezone"] == "UTC"
    assert data["display_timezone"] == "America/Chicago"
    assert data["h3_resolution"] == 8
    assert data["window_minutes"] == 15
    assert data["forecast_horizon_minutes"] == 30
    assert data["default_model"] == "xgboost"
    assert "xgboost" in data["available_models"]
    assert data["operational_zone_count"] >= 135
    assert data["total_catalog_zones"] >= 239

    # Source labels
    labels = data["source_labels"]
    assert labels["predicted_rides"] == "PREDICTED"
    assert labels["available_vehicles"] == "SIMULATED"
    assert labels["estimated_capacity"] == "SIMULATED_ESTIMATE"
    assert labels["demand_supply_pressure"] == "ESTIMATED"

    # Streaming & supply disclaimers
    assert "OFFLINE_PROTOTYPE" in data["streaming_status"]
    assert "SIMULATED_ESTIMATE" in data["supply_data_status"]
    assert "SIMULATED" in data["disclaimer"]


def test_metadata_zone_counts_consistency_and_definitions(client):
    """
    Regression test ensuring metadata zone counts strictly match distinct definitions:
      1. total_catalog_zones == 239 (all observed Resolution 8 cells in June catalog)
      2. retrospective_operational_zones == 139 (retrospective full-month >= 10 trips)
      3. forecast_eligible_zones == 135 (pre-test training >= 10 trips, zero-leakage)
      4. operational_zone_count == 135 (active operational zones served by API)
    """
    response = client.get("/api/v1/metadata")
    assert response.status_code == 200
    data = response.json()

    # Exact count assertions
    assert data["total_catalog_zones"] == 239
    assert data["retrospective_operational_zones"] == 139
    assert data["forecast_eligible_zones"] == 135
    assert data["operational_zone_count"] == 135

    # Relationship verification: 4 retrospective cells reached threshold only in test period
    assert data["retrospective_operational_zones"] - data["forecast_eligible_zones"] == 4
    assert data["total_catalog_zones"] > data["retrospective_operational_zones"]

    # Consistency with forecast and pressure endpoints
    r_fc = client.get("/api/v1/forecasts?limit=1")
    assert r_fc.status_code == 200
    # 135 zones x 863 origins = 116,505 records
    assert r_fc.json()["total_records"] == 135 * 863

    r_pr = client.get("/api/v1/pressure?limit=1")
    assert r_pr.status_code == 200
    assert r_pr.json()["total_records"] == 135 * 863


