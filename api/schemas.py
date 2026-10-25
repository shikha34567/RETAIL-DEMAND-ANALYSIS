"""
RideIntel Pydantic Schemas.

Strict response and request models conforming to contracts and documentation.
Guarantees UTC datetime handling and proper null serialization without NaNs.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ==============================================================================
# Common & Metadata Schemas
# ==============================================================================

class ComponentHealth(BaseModel):
    name: str
    status: str  # HEALTHY, DEGRADED, UNAVAILABLE
    path: str
    records: Optional[int] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str  # HEALTHY, DEGRADED, UNHEALTHY
    version: str = "0.1.0"
    timestamp: datetime
    components: List[ComponentHealth]


class MetadataResponse(BaseModel):
    dataset_period: str
    split_boundary_utc: str
    storage_timezone: str = "UTC"
    display_timezone: str = "America/Chicago"
    forecast_eligible_zones: int = Field(description="Leakage-safe zones eligible during training period and actively forecasted (135)")
    operational_zone_count: int = Field(description="Active forecast-eligible operational zone count (135)")
    retrospective_operational_zones: int = Field(description="Full-month retrospective qualification count from Phase 1 Task 6 (139)")
    total_catalog_zones: int = Field(description="Total observed H3 Resolution 8 cells in the historical catalog (239)")
    h3_resolution: int
    window_minutes: int
    forecast_horizon_minutes: int
    available_models: List[str]
    default_model: str
    source_labels: Dict[str, str]
    streaming_status: str
    supply_data_status: str
    disclaimer: str


# ==============================================================================
# Forecast Schemas
# ==============================================================================

class ForecastItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    forecast_id: str
    h3_cell: str
    forecast_origin: datetime
    target_start: datetime
    target_end: datetime
    predicted_rides: float
    model_name: str
    model_version: str
    forecast_status: str
    source_type: str = "PREDICTED"


class ForecastListResponse(BaseModel):
    total_records: int
    limit: int
    offset: int
    model_name: str
    data: List[ForecastItem]


# ==============================================================================
# Pressure Schemas
# ==============================================================================

class PressureItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    h3_cell: str
    forecast_origin: datetime
    target_start: datetime
    target_end: datetime
    model_name: str
    capacity_rate_r: float
    forecast_demand_rides_30m: float
    predicted_rides_D: float
    simulated_available_vehicles: int
    available_vehicles_V: int
    estimated_supply_capacity_rides_30m: float
    estimated_capacity_C: float
    demand_supply_ratio: Optional[float] = None
    pressure_index: Optional[float] = None
    estimated_unserved_demand_rides: float
    pressure_status: str
    pressure_level: str
    input_status: str
    supply_data_status: str = "SIMULATED_ESTIMATE"
    is_potential_surge: bool
    surge_severity: str
    source_type: str = "ESTIMATED"


class PressureListResponse(BaseModel):
    total_records: int
    limit: int
    offset: int
    data: List[PressureItem]


# ==============================================================================
# Surge Alert Schemas
# ==============================================================================

class SurgeAlertItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: str
    h3_cell: str
    detected_at: datetime
    forecast_origin: datetime
    observed_demand: int
    predicted_demand: float
    baseline_demand: Optional[float] = None
    severity: str
    simulation_run_id: str
    source_type: str = "SIMULATED_ESTIMATE"


class SurgeAlertListResponse(BaseModel):
    total_records: int
    limit: int
    offset: int
    disclaimer: str
    data: List[SurgeAlertItem]


# ==============================================================================
# Metrics Schemas
# ==============================================================================

class ModelMetricItem(BaseModel):
    model_name: str
    model_version: Optional[str] = "v1.0.0"
    count: int
    sum_actual: float
    mae: float
    rmse: float
    wape: Optional[float] = None
    wape_status: str


class MetricsResponse(BaseModel):
    evaluation_type: str = "HELD_OUT_TEST_SET"
    test_interval: Dict[str, Any]
    test_rows_per_model: int
    overall_metrics: Dict[str, ModelMetricItem]
    density_group_breakdown: Optional[Any] = None
    hourly_breakdown: Optional[Any] = None
    notes: str


# ==============================================================================
# Error Response Schema
# ==============================================================================

class ErrorResponse(BaseModel):
    detail: str
    error_code: str


# ==============================================================================
# Fleet Simulation Schemas
# ==============================================================================

class DriverItem(BaseModel):
    driver_id: str
    name: str
    status: str  # IDLE, REPOSITIONING, TO_PICKUP, WITH_PASSENGER, OFF_DUTY
    lat: float
    lng: float
    current_h3_cell: str
    destination_h3_cell: Optional[str] = None
    target_lat: Optional[float] = None
    target_lng: Optional[float] = None
    assigned_customer_id: Optional[str] = None
    route_progress: float = 0.0
    eta_seconds: int = 0
    reposition_cooldown_ticks: int = 0
    completed_trips_count: int = 0
    source_type: str = "SIMULATED"


class ZoneSupplyItem(BaseModel):
    h3_cell: str
    available_vehicles_V: int
    repositioning_incoming: int
    occupied_vehicles: int
    estimated_capacity_C: float
    predicted_demand_D: float
    estimated_unserved_demand: float
    pressure_level: str
    pressure_status: str


class CustomerRequestItem(BaseModel):
    request_id: str
    pickup_lat: float
    pickup_lng: float
    pickup_h3_cell: str
    dropoff_lat: float
    dropoff_lng: float
    dropoff_h3_cell: str
    status: str  # REQUESTED, ASSIGNED, PICKUP, ON_TRIP, COMPLETED, CANCELLED
    assigned_driver_id: Optional[str] = None
    created_at: str
    distance_km: float
    fare_estimate: float
    source_type: str = "SIMULATED"


class CreateCustomerRequestInput(BaseModel):
    pickup_h3_cell: str
    dropoff_h3_cell: str
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None


class SimulationFleetSummary(BaseModel):
    total_drivers: int
    idle_count: int
    repositioning_count: int
    to_pickup_count: int
    with_passenger_count: int
    off_duty_count: int


class SimulationEvent(BaseModel):
    event_id: str
    event_type: str
    sim_time: str
    message: str
    clock_tick: int
    driver_id: Optional[str] = None
    trip_id: Optional[str] = None
    zone_id: Optional[str] = None
    source_type: str = "SIMULATED"


class SimulationEventsResponse(BaseModel):
    events: List[SimulationEvent]
    total_events: int


class SimulationStateResponse(BaseModel):
    simulation_time: str
    clock_tick: int
    forecast_origin: str
    prediction_horizon: str
    fleet_summary: SimulationFleetSummary
    drivers: List[DriverItem]
    active_trips: List[CustomerRequestItem]
    completed_trips_count: int
    zone_supply: Dict[str, ZoneSupplyItem]
    recent_events: Optional[List[Dict[str, Any]]] = None
    current_sim_time: Optional[str] = None


class DispatchResultResponse(BaseModel):
    forecast_origin: str
    prediction_horizon: str
    drivers_considered: int
    drivers_assigned: int
    drivers_retained_coverage: int
    underserved_zones_before: int
    underserved_zones_after: int
    assignments: List[Dict[str, Any]]
    fleet_summary: SimulationFleetSummary
    drivers_evaluated: Optional[int] = None
    dispatched_count: Optional[int] = None
    retained_for_coverage: Optional[int] = None
    target_zones_considered: Optional[int] = None
    skipped_reasons: Optional[Dict[str, int]] = None
    deficit_hotspots_before: Optional[int] = None
    deficit_hotspots_after: Optional[int] = None
    limit_reached: Optional[bool] = None
    explanation: Optional[str] = None


class StepInput(BaseModel):
    seconds: int = Field(default=30, ge=1, le=300, description="Seconds to advance simulation clock")

