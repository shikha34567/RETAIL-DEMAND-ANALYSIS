"""
Unit tests for RideIntel Demand-Supply Pressure API endpoint.

Endpoint tested:
  - GET /api/v1/pressure
"""

import pytest
import math
from datetime import datetime
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_artifact_service
from api.config import APIConfig
from api.services.artifact_service import ArtifactService


@pytest.fixture
def client():
    return TestClient(app)


def test_pressure_list_basic(client):
    """Verifies GET /api/v1/pressure returns expected schema and total records."""
    response = client.get("/api/v1/pressure?limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 116505
    assert len(payload["data"]) == 10

    row = payload["data"][0]
    assert "h3_cell" in row
    assert "forecast_origin" in row
    assert "capacity_rate_r" in row
    assert "pressure_status" in row
    assert "pressure_level" in row
    assert "supply_data_status" in row
    assert row["source_type"] == "ESTIMATED"


def test_pressure_filter_by_level_and_null_index(client):
    """Verifies NO_CAPACITY records serialize ratio/index strictly as JSON null."""
    response = client.get("/api/v1/pressure?pressure_level=NO_CAPACITY&limit=20")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 39183
    assert len(payload["data"]) == 20

    for row in payload["data"]:
        assert row["pressure_level"] == "NO_CAPACITY"
        assert row["pressure_status"] == "NO_ESTIMATED_CAPACITY"
        assert row["estimated_capacity_C"] == 0.0
        assert row["available_vehicles_V"] == 0
        assert row["pressure_index"] is None
        assert row["demand_supply_ratio"] is None
        # Unserved demand when C=0 equals predicted demand
        assert row["estimated_unserved_demand_rides"] == row["predicted_rides_D"]


def test_pressure_filter_by_critical_level(client):
    """Verifies CRITICAL records have non-null pressure index >= 1.2."""
    response = client.get("/api/v1/pressure?pressure_level=CRITICAL&limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 90
    assert len(payload["data"]) == 10

    for row in payload["data"]:
        assert row["pressure_level"] == "CRITICAL"
        assert row["pressure_status"] == "HIGH_PRESSURE"
        assert row["pressure_index"] is not None
        assert row["pressure_index"] >= 1.20
        assert row["demand_supply_ratio"] is not None
        assert not math.isinf(row["pressure_index"])


def test_pressure_filter_by_zone(client):
    """Verifies zone filtering isolates records for a single H3 cell."""
    valid_zone = "882664cf21fffff"
    response = client.get(f"/api/v1/pressure?zone={valid_zone}&limit=50")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 863
    assert len(payload["data"]) == 50
    for row in payload["data"]:
        assert row["h3_cell"] == valid_zone


def test_pressure_invalid_zone_returns_404(client):
    """Verifies non-existent zone query returns HTTP 404."""
    response = client.get("/api/v1/pressure?zone=nonexistent_zone_123")
    assert response.status_code == 404
    assert "not found in zone universe" in response.json()["detail"]


def test_pressure_invalid_level_returns_400(client):
    """Verifies non-existent pressure level returns HTTP 400."""
    response = client.get("/api/v1/pressure?pressure_level=EXPLOSIVE")
    assert response.status_code == 400
    assert "Invalid pressure_level" in response.json()["detail"]


def test_pressure_invalid_time_range_returns_400(client):
    """Verifies start > end returns HTTP 400."""
    start = "2022-06-29T00:00:00Z"
    end = "2022-06-22T00:00:00Z"
    response = client.get(f"/api/v1/pressure?start={start}&end={end}")
    assert response.status_code == 400
    assert "before or equal to end timestamp" in response.json()["detail"]


def test_pressure_unserved_demand_non_negative(client):
    """Verifies estimated unserved demand is never negative."""
    response = client.get("/api/v1/pressure?limit=100")
    assert response.status_code == 200
    for row in response.json()["data"]:
        assert row["estimated_unserved_demand_rides"] >= 0.0


def test_pressure_missing_artifact_returns_503(client, tmp_path):
    """Verifies 503 is returned if pressure artifact cannot be loaded."""
    missing_cfg = APIConfig()
    missing_cfg.pressure_path = tmp_path / "missing_pressure.parquet"
    test_svc = ArtifactService(cfg=missing_cfg)

    app.dependency_overrides[get_artifact_service] = lambda: test_svc
    try:
        response = client.get("/api/v1/pressure")
        assert response.status_code == 503
        assert "Pressure status artifact missing" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_pressure_forecast_parity_for_known_zone(client):
    """
    Regression test verifying exact parity between /api/v1/pressure and /api/v1/forecasts
    for known zone (Zone Z-005, '8826641b23fffff') at origin '2022-06-22T05:00:00Z'.
    Proves that predicted_rides_D matches the authoritative persisted XGBoost forecast,
    distinguishes continuous predicted demand from integer observed rides (0), and verifies
    unserved shortage calculations.
    """
    origin = "2022-06-22T05:00:00Z"
    zone = "8826641b23fffff"  # Zone Z-005

    # 1. Fetch pressure record
    p_resp = client.get(f"/api/v1/pressure?zone={zone}&start={origin}&end={origin}&limit=1")
    assert p_resp.status_code == 200
    p_data = p_resp.json()["data"]
    assert len(p_data) == 1
    p_row = p_data[0]

    # 2. Fetch XGBoost forecast record
    f_resp = client.get(f"/api/v1/forecasts?zone={zone}&model=xgboost&start={origin}&end={origin}&limit=1")
    assert f_resp.status_code == 200
    f_data = f_resp.json()["data"]
    assert len(f_data) == 1
    f_row = f_data[0]

    # 3. Assert exact floating point parity
    assert p_row["predicted_rides_D"] == f_row["predicted_rides"]
    assert abs(p_row["predicted_rides_D"] - 0.3596688210964203) < 1e-9

    # 4. Assert NO_CAPACITY status and shortage equality
    assert p_row["pressure_level"] == "NO_CAPACITY"
    assert p_row["estimated_capacity_C"] == 0.0
    assert p_row["available_vehicles_V"] == 0
    assert p_row["estimated_unserved_demand_rides"] == p_row["predicted_rides_D"]


