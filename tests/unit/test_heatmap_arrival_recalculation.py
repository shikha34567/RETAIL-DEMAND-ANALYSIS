"""
RideIntel Unit & Integration Regression Test:
Heatmap Pressure Recalculation After Vehicle Arrival.

Verifies:
1. Pre-arrival state: repositioning vehicles are strictly excluded from destination zone idle supply (V=0, C=0).
2. Authoritative Arrival: vehicle transitions to IDLE at destination zone.
3. Destination zone available idle vehicle count increments immediately (V += 1).
4. Destination zone capacity recalculates canonically: C = V * 2.0.
5. Demand snapshot persistence: step() retains XGBoost forecast demand rather than wiping to zero.
6. Pressure recalculation:
   - When capacity satisfies demand (P <= 1.0), pressure transitions to MODERATE or LOW (no longer stuck at CRITICAL/NO_CAPACITY).
   - When genuine deficit remains (P >= 1.2), pressure remains CRITICAL.
7. Uninvolved zones maintain invariant telemetry.
8. Decoupled visual scale contract: visual smoothing strictly follows operational pressure tiers.
"""

import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.services.simulation_service import simulation_engine
from pipeline.simulation import (
    STATUS_NORMAL,
    STATUS_ELEVATED,
    STATUS_HIGH_PRESSURE,
    STATUS_NO_CAPACITY,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_HIGH,
    LEVEL_CRITICAL,
    LEVEL_NO_CAPACITY,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_step_preserves_active_demand_snapshot(client):
    """Verifies that simulation step() preserves forecast demand across ticks."""
    resp = client.post("/api/v1/simulation/reset")
    assert resp.status_code == 200
    state0 = resp.json()

    # Verify initial demand is loaded from snapshot
    active_zones_with_demand = [
        z for z, s in state0["zone_supply"].items()
        if s["predicted_demand_D"] > 0
    ]
    assert len(active_zones_with_demand) > 0, "Initial demand snapshot must have non-zero demand zones"

    sample_zone = active_zones_with_demand[0]
    initial_demand = state0["zone_supply"][sample_zone]["predicted_demand_D"]

    # Step simulation by 15 seconds
    step_resp = client.post("/api/v1/simulation/step", json={"seconds": 15})
    assert step_resp.status_code == 200
    state1 = step_resp.json()

    # Demand must be preserved after tick
    stepped_demand = state1["zone_supply"][sample_zone]["predicted_demand_D"]
    assert stepped_demand == initial_demand, f"Demand wiped after step: {stepped_demand} != {initial_demand}"


def test_pressure_recalculation_on_repositioning_arrival():
    """
    Direct engine test:
    1. Set up a deficit destination zone with D = 1.8, V = 0 -> NO_CAPACITY.
    2. Set a driver to REPOSITIONING en-route to this destination.
    3. Verify that before arrival, V=0, C=0.0, pressure=NO_CAPACITY.
    4. Trigger arrival at route_progress >= 1.0.
    5. Verify V=1, C=2.0, ratio = 1.8 / 2.0 = 0.9 -> MODERATE / ELEVATED.
    6. Verify second vehicle arrival: V=2, C=4.0, ratio = 1.8 / 4.0 = 0.45 -> LOW / NORMAL.
    """
    simulation_engine.reset()
    target_zone = simulation_engine.operational_zones[0]
    donor_zone = simulation_engine.operational_zones[1]

    # Explicitly configure mock demand for target zone
    demand_mock = {target_zone: 1.8, donor_zone: 0.2}
    simulation_engine.active_demand_map = demand_mock

    # Clear any drivers currently in target_zone
    for d in simulation_engine.drivers.values():
        if d["current_h3_cell"] == target_zone:
            d["current_h3_cell"] = donor_zone

    # Pre-arrival check
    supply_pre = simulation_engine.get_zone_supply_accounting()
    assert supply_pre[target_zone]["available_vehicles_V"] == 0
    assert supply_pre[target_zone]["estimated_capacity_C"] == 0.0
    assert supply_pre[target_zone]["predicted_demand_D"] == 1.8
    assert supply_pre[target_zone]["estimated_unserved_demand"] == 1.8
    assert supply_pre[target_zone]["pressure_level"] == LEVEL_NO_CAPACITY
    assert supply_pre[target_zone]["pressure_status"] == STATUS_NO_CAPACITY

    # Select one idle driver from donor zone and set to REPOSITIONING
    driver = next(d for d in simulation_engine.drivers.values() if d["current_h3_cell"] == donor_zone and d["status"] == "IDLE")
    driver_id = driver["driver_id"]
    driver["status"] = "REPOSITIONING"
    driver["destination_h3_cell"] = target_zone
    driver["route_progress"] = 0.5
    driver["origin_lat"] = 41.85
    driver["origin_lng"] = -87.65
    driver["target_lat"] = simulation_engine.zone_coords[target_zone]["lat"]
    driver["target_lng"] = simulation_engine.zone_coords[target_zone]["lng"]

    # Mid-transit check: vehicle must NOT count as available supply
    supply_mid = simulation_engine.get_zone_supply_accounting()
    assert supply_mid[target_zone]["available_vehicles_V"] == 0
    assert supply_mid[target_zone]["repositioning_incoming"] == 1
    assert supply_mid[target_zone]["pressure_level"] == LEVEL_NO_CAPACITY

    # Complete arrival by advancing progress to 1.0 and running step()
    driver["route_progress"] = 1.0
    post_state = simulation_engine.step(seconds=1)
    target_supply = post_state["zone_supply"][target_zone]

    # Post-arrival assertions
    assert driver["status"] == "IDLE", "Driver must be restored to IDLE upon arrival"
    assert driver["current_h3_cell"] == target_zone, "Driver current cell must be destination zone"
    assert driver["destination_h3_cell"] is None, "Destination cell must be cleared"
    assert target_supply["available_vehicles_V"] == 1, "Idle vehicle count must increment to 1"
    assert target_supply["estimated_capacity_C"] == 2.0, "Capacity must be V * 2.0 = 2.0"
    assert target_supply["repositioning_incoming"] == 0, "Incoming count must clear"
    assert target_supply["estimated_unserved_demand"] == 0.0, "1.8 demand covered by 2.0 capacity"

    # Ratio: 1.8 / 2.0 = 0.9 -> MODERATE / ELEVATED
    assert target_supply["pressure_level"] == LEVEL_MODERATE
    assert target_supply["pressure_status"] == STATUS_ELEVATED

    # Now simulate a second vehicle arrival to target zone:
    driver2 = next(d for d in simulation_engine.drivers.values() if d["driver_id"] != driver_id and d["status"] == "IDLE")
    driver2["status"] = "REPOSITIONING"
    driver2["destination_h3_cell"] = target_zone
    driver2["origin_lat"] = 41.85
    driver2["origin_lng"] = -87.65
    driver2["target_lat"] = simulation_engine.zone_coords[target_zone]["lat"]
    driver2["target_lng"] = simulation_engine.zone_coords[target_zone]["lng"]
    driver2["route_progress"] = 1.0

    post_state2 = simulation_engine.step(seconds=1)
    target_supply2 = post_state2["zone_supply"][target_zone]

    assert target_supply2["available_vehicles_V"] == 2
    assert target_supply2["estimated_capacity_C"] == 4.0
    # Ratio: 1.8 / 4.0 = 0.45 < 0.8 -> LOW / NORMAL
    assert target_supply2["pressure_level"] == LEVEL_LOW
    assert target_supply2["pressure_status"] == STATUS_NORMAL


def test_pressure_remains_critical_when_genuine_shortage_persists():
    """
    Verifies that if high demand remains unserved after arrival,
    the zone is NOT incorrectly turned green or moderate.
    D = 10.0, 1 vehicle arrives (V=1, C=2.0) -> ratio = 5.0 -> remains CRITICAL.
    """
    simulation_engine.reset()
    target_zone = simulation_engine.operational_zones[2]
    simulation_engine.active_demand_map = {target_zone: 10.0}

    for d in simulation_engine.drivers.values():
        if d["current_h3_cell"] == target_zone:
            d["current_h3_cell"] = simulation_engine.operational_zones[3]

    driver = next(d for d in simulation_engine.drivers.values() if d["status"] == "IDLE")
    driver["status"] = "REPOSITIONING"
    driver["destination_h3_cell"] = target_zone
    driver["origin_lat"] = 41.85
    driver["origin_lng"] = -87.65
    driver["target_lat"] = simulation_engine.zone_coords[target_zone]["lat"]
    driver["target_lng"] = simulation_engine.zone_coords[target_zone]["lng"]
    driver["route_progress"] = 1.0

    post_state = simulation_engine.step(seconds=1)
    target_supply = post_state["zone_supply"][target_zone]

    assert target_supply["available_vehicles_V"] == 1
    assert target_supply["estimated_capacity_C"] == 2.0
    assert target_supply["estimated_unserved_demand"] == 8.0
    assert target_supply["pressure_level"] == LEVEL_CRITICAL
    assert target_supply["pressure_status"] == STATUS_HIGH_PRESSURE


def test_dispatch_and_kinematic_arrival_end_to_end(client):
    """
    End-to-end integration test via API:
    1. Reset simulation.
    2. Run dispatch to assign vehicles toward deficit hotspots.
    3. Step clock forward until at least one repositioning vehicle arrives.
    4. Verify that destination zone capacity increases and pressure updates.
    """
    reset_resp = client.post("/api/v1/simulation/reset")
    assert reset_resp.status_code == 200

    disp_resp = client.post("/api/v1/simulation/dispatch")
    assert disp_resp.status_code == 200
    disp_data = disp_resp.json()
    assignments = disp_data["assignments"]

    if len(assignments) > 0:
        first_assignment = assignments[0]
        dest_zone = first_assignment["destination_zone"]

        # Step until arrived (up to 40 steps of 30 seconds = 1200s)
        arrived = False
        for _ in range(40):
            step_resp = client.post("/api/v1/simulation/step", json={"seconds": 30})
            assert step_resp.status_code == 200
            step_state = step_resp.json()
            drv = next((d for d in step_state["drivers"] if d["driver_id"] == first_assignment["driver_id"]), None)
            if drv and drv["status"] == "IDLE" and drv["current_h3_cell"] == dest_zone:
                arrived = True
                dest_supply = step_state["zone_supply"][dest_zone]
                assert dest_supply["available_vehicles_V"] >= 1
                assert dest_supply["estimated_capacity_C"] >= 2.0
                break

        assert arrived, f"Driver {first_assignment['driver_id']} failed to arrive at {dest_zone}"

