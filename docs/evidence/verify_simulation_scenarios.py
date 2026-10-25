import sys
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from api.main import app
from api.services.simulation_service import simulation_engine
import json

client = TestClient(app)

print("=== RIDEINTEL SECTION 11 SCENARIO VERIFICATION ===")

# --- SCENARIO A: PASSENGER TRIP LIFECYCLE ---
print("\n[SCENARIO A: Passenger Trip Lifecycle]")
client.post("/api/v1/simulation/reset")
z_pick = simulation_engine.operational_zones[0]
z_drop = simulation_engine.operational_zones[5]

# 1. Create request
req = client.post("/api/v1/simulation/customer-requests", json={
    "pickup_h3_cell": z_pick,
    "dropoff_h3_cell": z_drop
}).json()
req_id = req["request_id"]
d_id = req["assigned_driver_id"]
print(f"1. Request created: {req_id}, Assigned Rider: {d_id}, Status: {req['status']}")
assert req["status"] == "ASSIGNED"
assert simulation_engine.drivers[d_id]["status"] == "TO_PICKUP"

# 2. Advance to pickup
pickup_occurred = False
for step_idx in range(30):
    client.post("/api/v1/simulation/step", json={"seconds": 20})
    drv = simulation_engine.drivers[d_id]
    if drv["status"] == "WITH_PASSENGER":
        pickup_occurred = True
        print(f"2. Pickup reached at step {step_idx+1}! Rider status: WITH_PASSENGER")
        break
assert pickup_occurred, "Pickup did not occur within expected time"

# 3. Advance to dropoff
dropoff_occurred = False
for step_idx in range(120):
    client.post("/api/v1/simulation/step", json={"seconds": 60})
    drv = simulation_engine.drivers[d_id]
    if drv["status"] == "IDLE":
        dropoff_occurred = True
        print(f"3. Dropoff reached at step {step_idx+1}! Rider status: IDLE at zone {drv['current_h3_cell']}")
        break
assert dropoff_occurred, "Dropoff did not occur within expected time"
assert drv["current_h3_cell"] == z_drop, "Driver must be at dropoff zone"
assert drv["reposition_cooldown_ticks"] == 0, "Driver cooldown must be 0 after dropoff"

# 4. Check trip in completed history
trips_resp = client.get("/api/v1/simulation/trips").json()
comp_ids = [t["request_id"] for t in trips_resp["completed_trips"]]
assert req_id in comp_ids, "Trip must be in completed trips"
print(f"4. Trip {req_id} archived in completed trips history. SCENARIO A: PASS")

# --- SCENARIO B: FORECAST-DRIVEN REPOSITIONING ---
print("\n[SCENARIO B: Forecast-Driven Repositioning]")
client.post("/api/v1/simulation/reset")
# Occupy one driver with trip
req_b = client.post("/api/v1/simulation/customer-requests", json={
    "pickup_h3_cell": z_pick,
    "dropoff_h3_cell": z_drop
}).json()
busy_drv_id = req_b["assigned_driver_id"]

# Execute dispatch
disp = client.post("/api/v1/simulation/dispatch").json()
print(f"1. Evaluated: {disp['drivers_considered']}, Dispatched: {disp['drivers_assigned']}, Retained: {disp['drivers_retained_coverage']}")
assert disp["drivers_assigned"] > 0, "Must dispatch surplus drivers to deficit hotspots"

# Verify busy driver was NOT dispatched
disp_drv_ids = [a["driver_id"] for a in disp["assignments"]]
assert busy_drv_id not in disp_drv_ids, "Customer-serving driver must NOT be dispatched"
print(f"2. Busy driver {busy_drv_id} strictly excluded from repositioning dispatch")

# Verify events were generated
evts = client.get("/api/v1/simulation/events?limit=20").json()
assert evts["total_events"] > 0
disp_evts = [e for e in evts["events"] if e["event_type"] == "DISPATCH_ASSIGNED"]
assert len(disp_evts) > 0
print(f"3. Authoritative events emitted: \"{disp_evts[0]['message']}\"")
print("SCENARIO B: PASS")

# --- SCENARIO C: SQUARE GRID INTEGRITY ---
print("\n[SCENARIO C: Square Grid & Selection]")
with open("frontend/src/services/chicagoSquareGrid.json") as f:
    sq_data = json.load(f)
assert len(sq_data["features"]) == 105, "105 square cells"
all_cells = [c for f in sq_data["features"] for c in f["properties"]["h3_cells"]]
assert len(all_cells) == 239, "239 H3 cells"
assert len(all_cells) == len(set(all_cells)), "No double counting"
print(f"1. 105 square grid cells faithfully partition all 239 H3 zones with 0 overlaps")
print("SCENARIO C: PASS")

# --- SCENARIO D: CONTROLS & RECOVERY ---
print("\n[SCENARIO D: Controls & Recovery]")
reset_res = client.post("/api/v1/simulation/reset").json()
assert reset_res["clock_tick"] == 0
assert reset_res["fleet_summary"]["idle_count"] == 60
print("1. Simulation reset restores 60 idle vehicles and tick 0. SCENARIO D: PASS")

print("\nALL 4 SCENARIOS PASSED WITH AUTHORITATIVE EVIDENCE!")
