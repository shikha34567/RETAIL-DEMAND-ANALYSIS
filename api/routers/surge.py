"""
RideIntel Surge Alerts Router.

Endpoint:
  GET /api/v1/surge-alerts
"""

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status

from api.dependencies import get_artifact_service
from api.services.artifact_service import (
    ArtifactService,
    ArtifactUnavailableError,
    ResourceNotFoundError,
    InvalidParameterError
)
from api.schemas import SurgeAlertListResponse

router = APIRouter(prefix="/api/v1", tags=["Surge Alerts"])


@router.get(
    "/surge-alerts",
    response_model=SurgeAlertListResponse,
    summary="Retrieve Persisted Surge Alerts",
    description="Serves persisted surge alerts flagged when predicted demand exceeds service capacity and baseline thresholds."
)
def get_surge_alerts(
    zone: Optional[str] = Query(None, description="H3 Resolution 8 cell identifier"),
    start: Optional[datetime] = Query(None, description="Filter forecast_origin >= start (UTC)"),
    end: Optional[datetime] = Query(None, description="Filter forecast_origin <= end (UTC)"),
    severity: Optional[str] = Query(None, description="Filter by alert severity: HIGH, CRITICAL"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    try:
        total, data = svc.get_surge_alerts(
            zone=zone,
            start=start,
            end=end,
            severity=severity,
            limit=limit,
            offset=offset
        )
        return SurgeAlertListResponse(
            total_records=total,
            limit=limit,
            offset=offset,
            disclaimer=(
                "SIMULATED_ESTIMATE: Surge alerts are heuristic decision-support flags "
                "computed against simulated supply scenarios. They do not represent real-world price surges."
            ),
            data=data
        )
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except InvalidParameterError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ArtifactUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )

