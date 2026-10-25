"""
RideIntel Model Evaluation Metrics Router.

Endpoint:
  GET /api/v1/metrics
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status

from api.dependencies import get_artifact_service
from api.services.artifact_service import (
    ArtifactService,
    ArtifactUnavailableError,
    InvalidParameterError
)
from api.schemas import MetricsResponse

router = APIRouter(prefix="/api/v1", tags=["Model Evaluation Metrics"])


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Retrieve Held-Out Evaluation Metrics",
    description="Serves held-out test evaluation metrics (MAE, RMSE, WAPE) across identical test rows. Metrics are statically calculated from pre-saved evidence."
)
def get_metrics(
    model: Optional[str] = Query(None, description="Filter metrics for a specific model"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    try:
        return svc.get_metrics(model=model)
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

