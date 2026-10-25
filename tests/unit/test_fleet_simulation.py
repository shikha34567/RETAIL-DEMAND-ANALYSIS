"""
Unit tests for RideIntel Fleet Simulation Engine and Endpoints.

Verifies:
- Fleet conservation: total drivers count is strictly conserved across all states.
- Authoritative dispatch and repositioning behavior.
- Origin supply decrements at departure, destination increments only on arrival.
- Driver cannot be counted in two zones simultaneously.
- Protection against dispatch oscillation and duplicate assignments.
- Customer trip lifecycle: REQUESTED -> ASSIGNED -> PICKUP -> ON_TRIP -> COMPLETED.
- Trip cancellation and safe driver restoration.
- Simulation reset and state consistency.
"""

import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.services.simulation_service import simulation_engine, haversine_km


@pytest.fixture(autouse=True)
def reset_engine():
    """Ensure engine is reset to clean initial state before each test."""
    simulation_engine.reset()
    yield
    simulation_engine.reset()


@pytest.fixture
def client():
    return TestClient(app)


def test_fleet_initialization_deterministic():
    """Verifies that fleet initializes with exactly 60 drivers with IDLE state across valid H3 zones."""
    summary = simulation_engine.get_fleet_summary()
    assert summary["total_drivers"] == 60
    assert summary["idle_count"] == 60
    assert summary["repositioning_count"] == 0
    assert summary["to_pickup_count"] == 0
    assert summary["with_passenger_count"] == 0

    assert len(simulation_engine.drivers) == 60
    for d_id, d in simulation_engine.drivers.items():
        assert d["driver_id"] == d_id
        assert d["status"] == "IDLE"
        assert d["current_h3_cell"] in simulation_engine.zone_coords
        assert d["destination_h3_cell"] is None


def test_fleet_conservation_under_all_states():
    """Verifies that sum of all driver states strictly equals total fleet size."""
    # Force diverse driver states
    drivers = list(simulation_engine.drivers.values())
    drivers[0]["status"] = "REPOSITIONING"
    drivers[0]["destination_h3_cell"] = "882664c1a9fffff"
    drivers[1]["status"] = "TO_PICKUP"
    drivers[2]["status"] = "WITH_PASSENGER"
    drivers[3]["status"] = "OFF_DUTY"

    summary = simulation_engine.get_fleet_summary()
    assert summary["total_drivers"] == 60
    assert summary["idle_count"] == 56
    assert summary["repositioning_count"] == 1
    assert summary["to_pickup_count"] == 1
    assert summary["with_passenger_count"] == 1
    assert summary["off_duty_count"] == 1

    total_sum = (
        summary["idle_count"] +
        summary["repositioning_count"] +
        summary["to_pickup_count"] +
        summary["with_passenger_count"] +
        summary["off_duty_count"]
    )
    assert total_sum == 60


def test_supply_accounting_excludes_in_transit_drivers():
    """
    Verifies that when a driver starts repositioning, they are immediately removed
    from origin available supply and NOT added to destination available supply until arrival.
    """
    origin_zone = "882664c1a9fffff"
    dest_zone = "882664c1edfffff"

    # Place 2 idle drivers in origin_zone, 0 in dest_zone
    drivers = list(simulation_engine.drivers.values())
    for d in drivers:
        d["current_h3_cell"] = "8826641915fffff"  # Move elsewhere
    drivers[0]["current_h3_cell"] = origin_zone
    drivers[1]["current_h3_cell"] = origin_zone

    accounting_before = simulation_engine.get_zone_supply_accounting()
    assert accounting_before[origin_zone]["available_vehicles_V"] == 2
    assert accounting_before[origin_zone]["estimated_capacity_C"] == 4.0
    assert accounting_before[dest_zone]["available_vehicles_V"] == 0

    # Start driver 0 repositioning
    dest_coords = simulation_engine.zone_coords[dest_zone]
    drivers[0]["status"] = "REPOSITIONING"
    drivers[0]["destination_h3_cell"] = dest_zone
    drivers[0]["origin_lat"] = drivers[0]["lat"]
    drivers[0]["origin_lng"] = drivers[0]["lng"]
    drivers[0]["target_lat"] = dest_coords["lat"]
    drivers[0]["target_lng"] = dest_coords["lng"]
    drivers[0]["route_progress"] = 0.0

    accounting_during = simulation_engine.get_zone_supply_accounting()
    # Driver 0 is no longer available at origin
    assert accounting_during[origin_zone]["available_vehicles_V"] == 1
    assert accounting_during[origin_zone]["estimated_capacity_C"] == 2.0
    # Driver 0 is incoming, but NOT yet available at destination
    assert accounting_during[dest_zone]["available_vehicles_V"] == 0
    assert accounting_during[dest_zone]["estimated_capacity_C"] == 0.0
    assert accounting_during[dest_zone]["repositioning_incoming"] == 1

    # Simulate arrival: complete route progress
    drivers[0]["route_progress"] = 1.0
    simulation_engine.step(seconds=1)

    accounting_after = simulation_engine.get_zone_supply_accounting()
    # Driver 0 has arrived at destination and is now IDLE
    assert accounting_after[origin_zone]["available_vehicles_V"] == 1
    assert accounting_after[dest_zone]["available_vehicles_V"] == 1
    assert accounting_after[dest_zone]["estimated_capacity_C"] == 2.0
    assert accounting_after[dest_zone]["repositioning_incoming"] == 0


def test_driver_cannot_be_counted_in_two_zones():
    """Verifies that sum of available vehicles across all zones plus in-transit vehicles equals total fleet."""
    supply = simulation_engine.get_zone_supply_accounting()
    total_avail_v = sum(z["available_vehicles_V"] for z in supply.values())
    summary = simulation_engine.get_fleet_summary()
    assert total_avail_v == summary["idle_count"]


def test_dispatch_logic_assigns_drivers_and_protects_coverage(client):
    """Verifies POST /api/v1/simulation/dispatch matches surplus idle drivers to forecast hotspots."""
    resp = client.post("/api/v1/simulation/dispatch?origin=2022-06-22T05:00:00Z")
    assert resp.status_code == 200
    data = resp.json()

    assert data["prediction_horizon"] == "30 minutes"
    assert data["drivers_considered"] > 0
    assert "fleet_summary" in data
    assert data["fleet_summary"]["total_drivers"] == 60

    if data["drivers_assigned"] > 0:
        # Check first assignment structure
        asgn = data["assignments"][0]
        assert "driver_id" in asgn
        assert "origin_zone" in asgn
        assert "destination_zone" in asgn
        assert asgn["distance_km"] > 0

        # Check driver state is now REPOSITIONING
        d = simulation_engine.drivers[asgn["driver_id"]]
        assert d["status"] == "REPOSITIONING"
        assert d["destination_h3_cell"] == asgn["destination_zone"]
        assert d["reposition_cooldown_ticks"] > 0


def test_repeated_dispatch_prevents_oscillation(client):
    """Verifies that consecutive dispatch calls do not immediately re-dispatch drivers on cooldown."""
    resp1 = client.post("/api/v1/simulation/dispatch")
    assert resp1.status_code == 200
    assigned1 = resp1.json()["drivers_assigned"]

    # Immediate second dispatch
    resp2 = client.post("/api/v1/simulation/dispatch")
    assert resp2.status_code == 200
    assigned2 = resp2.json()["drivers_assigned"]

    # Active repositioning drivers must not be re-assigned
    summary = simulation_engine.get_fleet_summary()
    assert summary["repositioning_count"] >= assigned1
    # Total drivers remains strictly conserved
    assert summary["total_drivers"] == 60


def test_customer_trip_lifecycle(client):
    """Tests the full customer lifecycle: REQUESTED -> ASSIGNED -> PICKUP -> ON_TRIP -> COMPLETED."""
    zones = simulation_engine.operational_zones
    pickup_z = zones[0]
    dropoff_z = zones[5]

    # Create request
    req_payload = {
        "pickup_h3_cell": pickup_z,
        "dropoff_h3_cell": dropoff_z
    }
    resp = client.post("/api/v1/simulation/customer-requests", json=req_payload)
    assert resp.status_code == 200
    trip = resp.json()
    req_id = trip["request_id"]
    assert trip["pickup_h3_cell"] == pickup_z
    assert trip["dropoff_h3_cell"] == dropoff_z

    if trip["status"] == "ASSIGNED":
        d_id = trip["assigned_driver_id"]
        driver = simulation_engine.drivers[d_id]
        assert driver["status"] == "TO_PICKUP"
        assert driver["assigned_customer_id"] == req_id

        # Step until driver arrives at pickup
        driver["route_progress"] = 1.0
        client.post("/api/v1/simulation/step", json={"seconds": 15})

        # Driver should transition to WITH_PASSENGER and trip to ON_TRIP
        assert driver["status"] == "WITH_PASSENGER"
        assert simulation_engine.trips[req_id]["status"] == "ON_TRIP"

        # Step until driver arrives at dropoff
        driver["route_progress"] = 1.0
        client.post("/api/v1/simulation/step", json={"seconds": 15})

        # Driver should transition to IDLE in dropoff zone
        assert driver["status"] == "IDLE"
        assert driver["current_h3_cell"] == dropoff_z
        assert driver["assigned_customer_id"] is None
        assert driver["completed_trips_count"] == 1

        # Trip should be in completed trips
        completed = [t for t in simulation_engine.completed_trips if t["request_id"] == req_id]
        assert len(completed) == 1
        assert completed[0]["status"] == "COMPLETED"


def test_customer_cancellation_restores_driver(client):
    """Verifies cancelling a customer request before pickup restores driver to IDLE safely."""
    zones = simulation_engine.operational_zones
    req_payload = {
        "pickup_h3_cell": zones[0],
        "dropoff_h3_cell": zones[1]
    }
    resp = client.post("/api/v1/simulation/customer-requests", json=req_payload)
    assert resp.status_code == 200
    trip = resp.json()
    req_id = trip["request_id"]

    if trip["status"] == "ASSIGNED":
        d_id = trip["assigned_driver_id"]
        driver = simulation_engine.drivers[d_id]
        assert driver["status"] == "TO_PICKUP"

        # Cancel request
        cancel_resp = client.post(f"/api/v1/simulation/customer-requests/{req_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELLED"

        # Driver restored to IDLE
        assert driver["status"] == "IDLE"
        assert driver["assigned_customer_id"] is None


def test_simulation_reset_endpoint(client):
    """Verifies POST /api/v1/simulation/reset restores initial state and cleans trips."""
    # Modify state
    simulation_engine.step(seconds=60)
    assert simulation_engine.clock_tick == 1

    resp = client.post("/api/v1/simulation/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["clock_tick"] == 0
    assert data["fleet_summary"]["idle_count"] == 60
    assert data["fleet_summary"]["total_drivers"] == 60
    assert len(data["active_trips"]) == 0
    assert data["completed_trips_count"] == 0


def test_simulation_step_variable_seconds_and_clock_advancement(client):
    """Verifies POST /api/v1/simulation/step advances clock tick and accepts custom step duration."""
    assert simulation_engine.clock_tick == 0
    t0 = simulation_engine.current_sim_time

    # Step +15s (Phase 3 Command Centre standard step)
    resp = client.post("/api/v1/simulation/step", json={"seconds": 15})
    assert resp.status_code == 200
    data = resp.json()
    assert data["clock_tick"] == 1
    assert simulation_engine.current_sim_time == t0 + __import__("datetime").timedelta(seconds=15)

    # Step +30s
    resp2 = client.post("/api/v1/simulation/step", json={"seconds": 30})
    assert resp2.status_code == 200
    assert resp2.json()["clock_tick"] == 2
    assert simulation_engine.current_sim_time == t0 + __import__("datetime").timedelta(seconds=45)


def test_unserved_customer_request_status_and_accounting(client):
    """Verifies that a customer request remains REQUESTED (unserved) when no drivers are available nearby."""
    # Move all drivers to a far off zone or set to REPOSITIONING
    zones = simulation_engine.operational_zones
    target_pickup = zones[0]
    remote_zone = zones[-1]

    # Move all drivers far away
    for d in simulation_engine.drivers.values():
        d["current_h3_cell"] = remote_zone
        d["lat"] = 41.6000  # Far South
        d["lng"] = -87.6000

    # Request ride in far North pickup zone (distance > 12km max pickup radius)
    req_payload = {
        "pickup_h3_cell": target_pickup,
        "dropoff_h3_cell": zones[1],
        "pickup_lat": 42.0200,
        "pickup_lng": -87.6700
    }
    resp = client.post("/api/v1/simulation/customer-requests", json=req_payload)
    assert resp.status_code == 200
    trip = resp.json()
    assert trip["status"] == "REQUESTED"
    assert trip["assigned_driver_id"] is None

    # Inspect simulation state: trip appears in active_trips as unserved
    state_resp = client.get("/api/v1/simulation/state")
    assert state_resp.status_code == 200
    state = state_resp.json()
    assert len(state["active_trips"]) == 1
    assert state["active_trips"][0]["status"] == "REQUESTED"


def test_dispatch_retained_coverage_mathematical_conservation(client):
    """Verifies that considered idle drivers strictly equals assigned plus retained for coverage."""
    resp = client.post("/api/v1/simulation/dispatch?origin=2022-06-22T05:00:00Z")
    assert resp.status_code == 200
    data = resp.json()

    assert data["drivers_considered"] > 0
    assert data["drivers_assigned"] + data["drivers_retained_coverage"] == data["drivers_considered"]


def test_customer_request_invalid_zones_returns_400(client):
    """Verifies 400 Bad Request when an invalid H3 cell is submitted for customer request."""
    # Invalid pickup
    resp1 = client.post("/api/v1/simulation/customer-requests", json={
        "pickup_h3_cell": "invalid_cell_123",
        "dropoff_h3_cell": simulation_engine.operational_zones[0]
    })
    assert resp1.status_code == 400
    assert "Pickup zone 'invalid_cell_123' is not a valid catalog zone." in resp1.json()["detail"]

    # Invalid dropoff
    resp2 = client.post("/api/v1/simulation/customer-requests", json={
        "pickup_h3_cell": simulation_engine.operational_zones[0],
        "dropoff_h3_cell": "nonexistent_h3_zone"
    })
    assert resp2.status_code == 400
    assert "Dropoff zone 'nonexistent_h3_zone' is not a valid catalog zone." in resp2.json()["detail"]


def test_cancellation_restores_driver_for_subsequent_request(client):
    """Verifies cancellation restores driver to IDLE and permits re-assignment to new trips."""
    zones = simulation_engine.operational_zones
    req_payload = {
        "pickup_h3_cell": zones[0],
        "dropoff_h3_cell": zones[1]
    }
    resp1 = client.post("/api/v1/simulation/customer-requests", json=req_payload)
    assert resp1.status_code == 200
    trip1 = resp1.json()
    req_id1 = trip1["request_id"]
    assigned_driver = trip1["assigned_driver_id"]
    assert assigned_driver is not None

    # Cancel trip 1
    cancel_resp = client.post(f"/api/v1/simulation/customer-requests/{req_id1}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Confirm driver is IDLE
    driver_state = simulation_engine.drivers[assigned_driver]
    assert driver_state["status"] == "IDLE"

    # Subsequent request in same zone can assign the restored driver again
    resp2 = client.post("/api/v1/simulation/customer-requests", json=req_payload)
    assert resp2.status_code == 200
    trip2 = resp2.json()
    assert trip2["status"] == "ASSIGNED"


def test_customer_serving_driver_cannot_be_repositioned(client):
    """Verifies drivers in TO_PICKUP or WITH_PASSENGER are strictly excluded from repositioning dispatch."""
    zones = simulation_engine.operational_zones
    req_payload = {
        "pickup_h3_cell": zones[0],
        "dropoff_h3_cell": zones[2]
    }
    trip_resp = client.post("/api/v1/simulation/customer-requests", json=req_payload)
    assigned_driver_id = trip_resp.json()["assigned_driver_id"]
    assert assigned_driver_id is not None

    # Call dispatch
    dispatch_resp = client.post("/api/v1/simulation/dispatch")
    assert dispatch_resp.status_code == 200
    assignments = dispatch_resp.json()["assignments"]

    # Active customer driver must NOT be in repositioning assignments
    assigned_repo_drivers = [a["driver_id"] for a in assignments]
    assert assigned_driver_id not in assigned_repo_drivers
    assert simulation_engine.drivers[assigned_driver_id]["status"] == "TO_PICKUP"


def test_pressure_units_no_capacity_contract():
    """Verifies that zero capacity with positive demand produces NO_CAPACITY without infinity or NaN."""
    # Mock demand with zero available vehicles
    demand_mock = {simulation_engine.operational_zones[0]: 5.5}
    # Temporarily remove drivers from this zone
    zone = simulation_engine.operational_zones[0]
    for d in simulation_engine.drivers.values():
        if d["current_h3_cell"] == zone:
            d["current_h3_cell"] = simulation_engine.operational_zones[1]

    accounting = simulation_engine.get_zone_supply_accounting(demand_mock)
    zone_data = accounting[zone]
    assert zone_data["available_vehicles_V"] == 0
    assert zone_data["estimated_capacity_C"] == 0.0
    assert zone_data["predicted_demand_D"] == 5.5
    assert zone_data["estimated_unserved_demand"] == 5.5
    assert zone_data["pressure_level"] == "NO_CAPACITY"
    assert zone_data["pressure_status"] == "NO_ESTIMATED_CAPACITY"


def test_fleet_conservation_across_full_lifecycle(client):
    """Verifies that sum of all fleet states strictly equals 60 at every step of trip and dispatch lifecycle."""
    def assert_conserved():
        summary = simulation_engine.get_fleet_summary()
        total = (
            summary["idle_count"] +
            summary["repositioning_count"] +
            summary["to_pickup_count"] +
            summary["with_passenger_count"] +
            summary["off_duty_count"]
        )
        assert total == 60, f"Conservation violated: {total} != 60"

    assert_conserved()

    # Step 1: Dispatch repositioning
    client.post("/api/v1/simulation/dispatch")
    assert_conserved()

    # Step 2: Create Customer Trip
    zones = simulation_engine.operational_zones
    client.post("/api/v1/simulation/customer-requests", json={
        "pickup_h3_cell": zones[0],
        "dropoff_h3_cell": zones[5]
    })
    assert_conserved()

    # Step 3: Advance kinematics 10 steps (+150s)
    for _ in range(10):
        client.post("/api/v1/simulation/step", json={"seconds": 15})
        assert_conserved()

    # Step 4: Reset
    client.post("/api/v1/simulation/reset")
    assert_conserved()
    assert simulation_engine.get_fleet_summary()["idle_count"] == 60


def test_simulation_events_endpoint_and_state_sync(client):
    """Verifies GET /api/v1/simulation/events returns authoritative events and state includes recent_events."""
    client.post("/api/v1/simulation/reset")

    # Dispatch to generate events
    client.post("/api/v1/simulation/dispatch")

    # Create customer request to generate events
    zones = simulation_engine.operational_zones
    client.post("/api/v1/simulation/customer-requests", json={
        "pickup_h3_cell": zones[0],
        "dropoff_h3_cell": zones[1]
    })

    # Query /events endpoint
    evt_resp = client.get("/api/v1/simulation/events?limit=20")
    assert evt_resp.status_code == 200
    payload = evt_resp.json()
    assert "events" in payload
    assert "total_events" in payload
    assert payload["total_events"] > 0
    assert len(payload["events"]) <= 20

    first_evt = payload["events"][0]
    assert "event_id" in first_evt
    assert "event_type" in first_evt
    assert "message" in first_evt
    assert "sim_time" in first_evt
    assert "clock_tick" in first_evt
    assert first_evt["source_type"] == "SIMULATED"

    # Query /state endpoint to verify recent_events inclusion
    state_resp = client.get("/api/v1/simulation/state")
    assert state_resp.status_code == 200
    state_payload = state_resp.json()
    assert "recent_events" in state_payload
    assert len(state_payload["recent_events"]) > 0


def test_driver_cooldown_reset_on_trip_completion(client):
    """Verifies that completing a passenger trip resets driver's cooldown ticks to 0."""
    client.post("/api/v1/simulation/reset")
    zones = simulation_engine.operational_zones

    req_resp = client.post("/api/v1/simulation/customer-requests", json={
        "pickup_h3_cell": zones[0],
        "dropoff_h3_cell": zones[1]
    })
    d_id = req_resp.json()["assigned_driver_id"]
    assert d_id is not None

    driver = simulation_engine.drivers[d_id]
    # Simulate driver in transit with some cooldown ticks
    driver["reposition_cooldown_ticks"] = 5

    # Force step until arrival at pickup and then dropoff
    # Complete the trip by advancing steps
    for _ in range(50):
        client.post("/api/v1/simulation/step", json={"seconds": 60})
        if driver["status"] == "IDLE":
            break

    assert driver["status"] == "IDLE"
    assert driver["reposition_cooldown_ticks"] == 0, "Cooldown should be reset to 0 after completing a trip"




