"""
RideIntel Backend API Main Application.

Entry point for the FastAPI backend service serving Phase 1-4 data artifacts.
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import config
from api.routers import health, forecasts, pressure, surge, metrics, simulation
from api.services.artifact_service import (
    ArtifactUnavailableError,
    ResourceNotFoundError,
    InvalidParameterError
)

app = FastAPI(
    title="RideIntel API",
    description=(
        "Decision-support backend for Chicago Ride Demand Analysis. "
        "Serves demand forecasts, simulated vehicle supply, demand-supply pressure evaluations, "
        "and surge detection alerts derived from Phase 1-4 pipeline artifacts."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ------------------------------------------------------------------------------
# CORS Middleware
# ------------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Exception Handlers
# ------------------------------------------------------------------------------

@app.exception_handler(ResourceNotFoundError)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "error_code": "RESOURCE_NOT_FOUND"}
    )


@app.exception_handler(InvalidParameterError)
async def invalid_parameter_handler(request: Request, exc: InvalidParameterError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error_code": "INVALID_PARAMETER"}
    )


@app.exception_handler(ArtifactUnavailableError)
async def artifact_unavailable_handler(request: Request, exc: ArtifactUnavailableError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc), "error_code": "ARTIFACT_UNAVAILABLE"}
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # Hide internal stack traces and filesystem paths from external API consumers
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred while processing the request.", "error_code": "INTERNAL_ERROR"}
    )


# ------------------------------------------------------------------------------
# Register Routers
# ------------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(forecasts.router)
app.include_router(pressure.router)
app.include_router(surge.router)
app.include_router(metrics.router)
app.include_router(simulation.router)


@app.get("/", tags=["Root"])
def root_info():
    """Root metadata and entry point link."""
    return {
        "service": "RideIntel API",
        "version": "0.1.0",
        "docs_url": "/docs",
        "health_check": "/api/v1/health",
        "metadata": "/api/v1/metadata"
    }

