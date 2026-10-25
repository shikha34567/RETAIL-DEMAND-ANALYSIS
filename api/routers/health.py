"""
RideIntel Health and Metadata Router.

Endpoints:
  GET /api/v1/health
  GET /api/v1/metadata
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from api.dependencies import get_artifact_service
from api.services.artifact_service import ArtifactService, ArtifactUnavailableError
from api.schemas import HealthResponse, MetadataResponse

router = APIRouter(prefix="/api/v1", tags=["Health & Metadata"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application and Artifact Health Check",
    description="Inspects artifact storage accessibility and returns component health status. Returns 503 if critical files are unavailable."
)
def get_health(svc: ArtifactService = Depends(get_artifact_service)):
    health_data = svc.check_health()
    if health_data.status == "UNHEALTHY":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_data.model_dump(mode="json")
        )
    return health_data


@router.get(
    "/metadata",
    response_model=MetadataResponse,
    summary="Project Dataset and Parameter Metadata",
    description="Returns temporal boundaries, timezone conventions, operational zone count, model identifiers, and simulation disclaimers."
)
def get_metadata(svc: ArtifactService = Depends(get_artifact_service)):
    try:
        return svc.get_metadata()
    except ArtifactUnavailableError as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(e), "error_code": "ARTIFACT_UNAVAILABLE"}
        )

