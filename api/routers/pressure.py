"""
RideIntel Demand-Supply Pressure Router.

Endpoint:
  GET /api/v1/pressure
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
from api.schemas import PressureListResponse

router = APIRouter(prefix="/api/v1", tags=["Demand-Supply Pressure"])


@router.get(
    "/pressure",
    response_model=PressureListResponse,
    summary="Retrieve Zone Demand-Supply Pressure Records",
    description="Serves demand-supply pressure evaluation records. Includes forecast demand, simulated vehicle count, capacity, ratios, and unserved demand."
)
def get_pressure(
    zone: Optional[str] = Query(None, description="H3 Resolution 8 cell identifier"),
    start: Optional[datetime] = Query(None, description="Filter forecast_origin >= start (UTC)"),
    end: Optional[datetime] = Query(None, description="Filter forecast_origin <= end (UTC)"),
    pressure_level: Optional[str] = Query(None, description="Filter by pressure level: LOW, MODERATE, HIGH, CRITICAL, NO_CAPACITY"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    try:
        total, data = svc.get_pressure(
            zone=zone,
            start=start,
            end=end,
            pressure_level=pressure_level,
            limit=limit,
            offset=offset
        )
        return PressureListResponse(
            total_records=total,
            limit=limit,
            offset=offset,
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

