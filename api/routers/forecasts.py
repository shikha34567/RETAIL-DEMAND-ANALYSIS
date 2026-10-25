"""
RideIntel Demand Forecasts Router.

Endpoint:
  GET /api/v1/forecasts
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
from api.schemas import ForecastListResponse

router = APIRouter(prefix="/api/v1", tags=["Demand Forecasts"])


@router.get(
    "/forecasts",
    response_model=ForecastListResponse,
    summary="Retrieve Zone Demand Forecasts",
    description="Serves 30-minute forward demand forecasts per H3 zone. Supports model selection, zone filtering, time ranges, and pagination."
)
def get_forecasts(
    model: str = Query("xgboost", description="Model identifier: xgboost, baseline_rolling_avg, baseline_same_time_last_week"),
    zone: Optional[str] = Query(None, description="H3 Resolution 8 cell identifier"),
    start: Optional[datetime] = Query(None, description="Filter forecast_origin >= start (UTC)"),
    end: Optional[datetime] = Query(None, description="Filter forecast_origin <= end (UTC)"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    try:
        total, data = svc.get_forecasts(
            model=model,
            zone=zone,
            start=start,
            end=end,
            limit=limit,
            offset=offset
        )
        return ForecastListResponse(
            total_records=total,
            limit=limit,
            offset=offset,
            model_name=model,
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

