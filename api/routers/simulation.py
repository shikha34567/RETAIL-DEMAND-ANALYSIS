"""
RideIntel Fleet Simulation Router.

Endpoints:
  GET  /api/v1/simulation/state
  POST /api/v1/simulation/reset
  POST /api/v1/simulation/dispatch
  POST /api/v1/simulation/step
  POST /api/v1/simulation/customer-requests
  POST /api/v1/simulation/customer-requests/{request_id}/cancel
  GET  /api/v1/simulation/trips
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status

from api.dependencies import get_artifact_service
from api.services.artifact_service import ArtifactService
from api.services.simulation_service import simulation_engine
from api.schemas import (
    SimulationStateResponse,
    DispatchResultResponse,
    StepInput,
    CustomerRequestItem,
    CreateCustomerRequestInput,
    SimulationEventsResponse
)

router = APIRouter(prefix="/api/v1/simulation", tags=["Fleet Simulation Command Centre"])


@router.get(
    "/state",
    response_model=SimulationStateResponse,
    summary="Retrieve Authoritative Simulation State",
    description="Returns current simulation clock, fleet breakdown, driver positions/states, active trips, and zone supply accounting."
)
def get_simulation_state(
    origin: Optional[str] = Query(None, description="Forecast origin timestamp to calculate zone demand"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    demand_map = None
    if origin:
        try:
            _, fc_records = svc.get_forecasts(
                model="xgboost",
                start=datetime.fromisoformat(origin.replace("Z", "+00:00")),
                end=datetime.fromisoformat(origin.replace("Z", "+00:00")),
                limit=150
            )
            demand_map = {r["h3_cell"]: float(r["predicted_rides"]) for r in fc_records}
        except Exception:
            demand_map = None

    state = simulation_engine.get_state(demand_map)
    return SimulationStateResponse(**state)


@router.post(
    "/reset",
    response_model=SimulationStateResponse,
    summary="Reset Simulation to Initial State",
    description="Resets the simulated fleet to deterministic initial coordinates across valid Chicago H3 zones and clears all trips."
)
def reset_simulation(
    origin: Optional[str] = Query(None, description="Forecast origin timestamp to initialize demand accounting"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    simulation_engine.reset(origin_str=origin)
    demand_map = None
    if origin:
        try:
            _, fc_records = svc.get_forecasts(
                model="xgboost",
                start=datetime.fromisoformat(origin.replace("Z", "+00:00")),
                end=datetime.fromisoformat(origin.replace("Z", "+00:00")),
                limit=150
            )
            demand_map = {r["h3_cell"]: float(r["predicted_rides"]) for r in fc_records}
        except Exception:
            demand_map = None
    state = simulation_engine.get_state(demand_map)
    return SimulationStateResponse(**state)


@router.post(
    "/dispatch",
    response_model=DispatchResultResponse,
    summary="Execute Authoritative Fleet Dispatch & Repositioning",
    description="Invokes real dispatch logic matching surplus idle drivers with forecast demand deficit hotspots, enforcing origin coverage floors and destination limits."
)
def run_dispatch(
    origin: Optional[str] = Query(None, description="Forecast origin timestamp (defaults to current active snapshot)"),
    svc: ArtifactService = Depends(get_artifact_service)
):
    result = simulation_engine.dispatch(artifact_service=svc, origin_str=origin)
    return DispatchResultResponse(**result)


@router.post(
    "/step",
    response_model=SimulationStateResponse,
    summary="Advance Simulation Clock",
    description="Advances the simulation clock by specified seconds, progressing in-transit vehicles and resolving customer trip arrivals."
)
def step_simulation(
    input_data: StepInput
):
    state = simulation_engine.step(seconds=input_data.seconds)
    return SimulationStateResponse(**state)


@router.post(
    "/customer-requests",
    response_model=CustomerRequestItem,
    summary="Create Simulated Customer Request",
    description="Creates a simulated customer ride request and attempts to match the nearest eligible idle driver."
)
def create_customer_request(
    payload: CreateCustomerRequestInput
):
    try:
        trip = simulation_engine.create_customer_request(
            pickup_h3_cell=payload.pickup_h3_cell,
            dropoff_h3_cell=payload.dropoff_h3_cell,
            pickup_lat=payload.pickup_lat,
            pickup_lng=payload.pickup_lng,
            dropoff_lat=payload.dropoff_lat,
            dropoff_lng=payload.dropoff_lng
        )
        return CustomerRequestItem(**trip)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/customer-requests/{request_id}/cancel",
    response_model=CustomerRequestItem,
    summary="Cancel Customer Ride Request",
    description="Cancels an active customer request prior to pickup, safely restoring the assigned driver to IDLE."
)
def cancel_customer_request(request_id: str):
    try:
        trip = simulation_engine.cancel_customer_request(request_id)
        return CustomerRequestItem(**trip)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/trips",
    summary="Retrieve Active and Completed Customer Trips",
    description="Returns lists of currently active and completed customer trips."
)
def get_trips():
    return {
        "active_trips": list(simulation_engine.trips.values()),
        "completed_trips": simulation_engine.completed_trips,
        "total_active": len(simulation_engine.trips),
        "total_completed": len(simulation_engine.completed_trips)
    }


@router.get(
    "/events",
    response_model=SimulationEventsResponse,
    summary="Retrieve Authoritative Simulation Operational Events",
    description="Returns real-time operational events from dispatch assignments, customer requests, and trip completions."
)
def get_simulation_events(
    limit: int = Query(50, ge=1, le=200, description="Maximum number of recent events to return")
):
    events = simulation_engine.get_events(limit=limit)
    return SimulationEventsResponse(
        events=events,
        total_events=len(simulation_engine.events)
    )


