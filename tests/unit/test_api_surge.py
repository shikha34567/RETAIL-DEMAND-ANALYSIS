"""
Unit tests for RideIntel Surge Alerts API endpoint.

Endpoint tested:
  - GET /api/v1/surge-alerts
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


def test_surge_alerts_list_all(client):
    """Verifies GET /api/v1/surge-alerts returns all 8 persisted alerts."""
    response = client.get("/api/v1/surge-alerts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 8
    assert len(payload["data"]) == 8
    assert "SIMULATED_ESTIMATE" in payload["disclaimer"]

    for alert in payload["data"]:
        assert alert["alert_id"].startswith("alert-")
        assert alert["predicted_demand"] >= 5.0
        assert alert["severity"] in {"HIGH", "CRITICAL"}
        assert alert["source_type"] == "SIMULATED_ESTIMATE"


def test_surge_alerts_filter_by_severity(client):
    """Verifies severity filtering isolates HIGH (5) and CRITICAL (3) alerts."""
    r_high = client.get("/api/v1/surge-alerts?severity=HIGH")
    assert r_high.status_code == 200
    p_high = r_high.json()
    assert p_high["total_records"] == 5
    for a in p_high["data"]:
        assert a["severity"] == "HIGH"

    r_crit = client.get("/api/v1/surge-alerts?severity=CRITICAL")
    assert r_crit.status_code == 200
    p_crit = r_crit.json()
    assert p_crit["total_records"] == 3
    for a in p_crit["data"]:
        assert a["severity"] == "CRITICAL"


def test_surge_alerts_invalid_severity_returns_400(client):
    """Verifies invalid severity string returns HTTP 400."""
    response = client.get("/api/v1/surge-alerts?severity=MODERATE")
    assert response.status_code == 400
    assert "Invalid severity" in response.json()["detail"]


def test_surge_alerts_filter_by_zone(client):
    """Verifies filtering alerts for a specific zone."""
    # Zone 882664cf21fffff has 3 alerts
    target_zone = "882664cf21fffff"
    response = client.get(f"/api/v1/surge-alerts?zone={target_zone}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_records"] == 3
    for a in payload["data"]:
        assert a["h3_cell"] == target_zone


def test_surge_alerts_invalid_zone_returns_404(client):
    """Verifies unknown zone returns HTTP 404."""
    response = client.get("/api/v1/surge-alerts?zone=unknown_zone_888")
    assert response.status_code == 404
    assert "not found in zone universe" in response.json()["detail"]


def test_surge_alerts_missing_artifact_returns_503(client, tmp_path):
    """Verifies 503 is returned if surge artifact cannot be loaded."""
    missing_cfg = APIConfig()
    missing_cfg.surge_alerts_path = tmp_path / "missing_surge.parquet"
    test_svc = ArtifactService(cfg=missing_cfg)

    app.dependency_overrides[get_artifact_service] = lambda: test_svc
    try:
        response = client.get("/api/v1/surge-alerts")
        assert response.status_code == 503
        assert "Surge alerts artifact missing" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()

