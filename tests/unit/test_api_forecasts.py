"""
Unit tests for RideIntel Demand Forecasts API endpoint.

Endpoint tested:
  - GET /api/v1/forecasts
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_artifact_service
from api.config import APIConfig
from api.services.artifact_service import ArtifactService


@pytest.fixture
def client():
    return TestClient(app)


def test_forecasts_defaults_to_xgboost(client):
    """Verifies default request selects xgboost and returns valid page."""
    response = client.get("/api/v1/forecasts?limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["model_name"] == "xgboost"
    assert payload["total_records"] == 116505
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert len(payload["data"]) == 10

    # Inspect first record
    row = payload["data"][0]
    assert row["model_name"] == "xgboost"
    assert row["source_type"] == "PREDICTED"
    assert isinstance(row["predicted_rides"], float)
    assert row["forecast_origin"].endswith("Z") or "+00:00" in row["forecast_origin"]


def test_forecasts_filter_by_model(client):
    """Verifies querying baseline models returns corresponding predictions."""
    for model in ["baseline_rolling_avg", "baseline_same_time_last_week"]:
        response = client.get(f"/api/v1/forecasts?model={model}&limit=5")
        assert response.status_code == 200
        payload = response.json()
        assert payload["model_name"] == model
        assert payload["total_records"] == 116505
        assert len(payload["data"]) == 5
        for row in payload["data"]:
            assert row["model_name"] == model


def test_forecasts_filter_by_zone(client):
    """Verifies zone filtering isolates records for a single H3 cell."""
    valid_zone = "882664cf21fffff"
    response = client.get(f"/api/v1/forecasts?zone={valid_zone}&limit=50")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 863  # 863 origins for this zone
    assert len(payload["data"]) == 50
    for row in payload["data"]:
        assert row["h3_cell"] == valid_zone


def test_forecasts_invalid_zone_returns_404(client):
    """Verifies querying an unknown H3 cell returns HTTP 404."""
    response = client.get("/api/v1/forecasts?zone=nonexistent_h3_zone_xyz")
    assert response.status_code == 404
    payload = response.json()
    assert "not found in zone universe" in payload["detail"]


def test_forecasts_invalid_model_returns_400(client):
    """Verifies querying an unknown model identifier returns HTTP 400."""
    response = client.get("/api/v1/forecasts?model=lstm_neural_net")
    assert response.status_code == 400
    payload = response.json()
    assert "not recognized" in payload["detail"]


def test_forecasts_time_range_filter(client):
    """Verifies time filtering constrains returned forecast origins."""
    start = "2022-06-25T00:00:00Z"
    end = "2022-06-25T12:00:00Z"
    response = client.get(f"/api/v1/forecasts?start={start}&end={end}&limit=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] > 0
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))

    for row in payload["data"]:
        row_dt = datetime.fromisoformat(row["forecast_origin"])
        assert start_dt <= row_dt <= end_dt


def test_forecasts_invalid_time_range_returns_400(client):
    """Verifies start > end returns HTTP 400."""
    start = "2022-06-28T00:00:00Z"
    end = "2022-06-25T00:00:00Z"
    response = client.get(f"/api/v1/forecasts?start={start}&end={end}")
    assert response.status_code == 400
    payload = response.json()
    assert "before or equal to end timestamp" in payload["detail"]


def test_forecasts_pagination_and_bounds(client):
    """Verifies offset shifts records and limit is capped at 1000."""
    r1 = client.get("/api/v1/forecasts?limit=5&offset=0")
    r2 = client.get("/api/v1/forecasts?limit=5&offset=5")
    assert r1.status_code == 200 and r2.status_code == 200
    ids_page1 = [r["forecast_id"] for r in r1.json()["data"]]
    ids_page2 = [r["forecast_id"] for r in r2.json()["data"]]
    assert set(ids_page1).isdisjoint(set(ids_page2))

    # Test limit exceeding maximum
    r_over = client.get("/api/v1/forecasts?limit=5000")
    assert r_over.status_code == 422  # Pydantic validation error


def test_forecasts_missing_artifact_returns_503(client, tmp_path):
    """Verifies 503 is returned if forecasts artifact cannot be loaded."""
    missing_cfg = APIConfig()
    missing_cfg.forecasts_path = tmp_path / "missing_forecasts.parquet"
    test_svc = ArtifactService(cfg=missing_cfg)

    app.dependency_overrides[get_artifact_service] = lambda: test_svc
    try:
        response = client.get("/api/v1/forecasts")
        assert response.status_code == 503
        assert "Forecasts artifact missing" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()

