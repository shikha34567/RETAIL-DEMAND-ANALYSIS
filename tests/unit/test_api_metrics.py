"""
Unit tests for RideIntel Model Evaluation Metrics API endpoint.

Endpoint tested:
  - GET /api/v1/metrics
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_artifact_service
from api.config import APIConfig
from api.services.artifact_service import ArtifactService


@pytest.fixture
def client():
    return TestClient(app)


def test_metrics_overall_response(client):
    """Verifies GET /api/v1/metrics returns held-out metrics across all 3 models."""
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert payload["evaluation_type"] == "HELD_OUT_TEST_SET"
    assert payload["test_rows_per_model"] == 116505
    assert "start" in payload["test_interval"]
    assert "end" in payload["test_interval"]

    models = payload["overall_metrics"]
    expected_models = {"xgboost", "baseline_rolling_avg", "baseline_same_time_last_week"}
    assert set(models.keys()) == expected_models

    # XGBoost specific values check against Phase 3 final audit
    xgb = models["xgboost"]
    assert xgb["count"] == 116505
    assert abs(xgb["mae"] - 0.9310) < 0.01
    assert abs(xgb["rmse"] - 2.2366) < 0.01
    assert abs(xgb["wape"] - 0.3186) < 0.01
    assert xgb["wape_status"] == "VALID"

    # Baselines
    assert models["baseline_rolling_avg"]["mae"] > xgb["mae"]
    assert models["baseline_same_time_last_week"]["mae"] > xgb["mae"]


def test_metrics_filter_by_model(client):
    """Verifies model query parameter filters response to a single model."""
    response = client.get("/api/v1/metrics?model=xgboost")
    assert response.status_code == 200
    payload = response.json()
    assert list(payload["overall_metrics"].keys()) == ["xgboost"]


def test_metrics_invalid_model_returns_400(client):
    """Verifies unknown model query returns HTTP 400."""
    response = client.get("/api/v1/metrics?model=random_forest")
    assert response.status_code == 400
    assert "not found in evaluation metrics" in response.json()["detail"]


def test_metrics_missing_artifact_returns_503(client, tmp_path):
    """Verifies 503 is returned if evaluation artifact cannot be loaded."""
    missing_cfg = APIConfig()
    missing_cfg.evaluation_summary_path = tmp_path / "missing_summary.json"
    test_svc = ArtifactService(cfg=missing_cfg)

    app.dependency_overrides[get_artifact_service] = lambda: test_svc
    try:
        response = client.get("/api/v1/metrics")
        assert response.status_code == 503
        assert "evaluation summary missing" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()

