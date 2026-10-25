"""
RideIntel Fleet Simulation Service.

Authoritative in-memory simulation engine managing:
- Deterministic fleet state across H3 Resolution 8 zones.
- Authoritative dispatch/repositioning logic responding to predicted demand.
- Customer trip lifecycle: REQUESTED -> ASSIGNED -> PICKUP -> ON_TRIP -> COMPLETED.
- Strict fleet conservation and zone supply accounting.
"""

import math
import json
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

import h3

from api.services.artifact_service import ArtifactService


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two coordinates in kilometers."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


class FleetSimulationEngine:
    def __init__(self, fleet_size: int = 60, seed: int = 42):
        self.fleet_size = fleet_size
        self.seed = seed
        self.clock_tick = 0
        self.sim_start_time = datetime(2022, 6, 22, 5, 0, 0, tzinfo=timezone.utc)
        self.current_sim_time = self.sim_start_time
        self.forecast_origin_str = "2022-06-22T05:00:00Z"

        # Zone geometry cache (cell -> {lat, lng, label})
        self.zone_coords: Dict[str, Dict[str, Any]] = {}
        self.operational_zones: List[str] = []

        # Simulation entities
        self.drivers: Dict[str, Dict[str, Any]] = {}
        self.trips: Dict[str, Dict[str, Any]] = {}
        self.completed_trips: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.active_demand_map: Dict[str, float] = {}

        self._load_zone_cache()
        self.reset()

    def load_demand_snapshot(self, origin_str: Optional[str] = None):
        """Loads authoritative XGBoost predicted demand for snapshot origin."""
        target_origin = origin_str or self.forecast_origin_str
        try:
            from api.services.artifact_service import service as default_artifact_service
            total_fc, fc_records = default_artifact_service.get_forecasts(
                model="xgboost",
                start=datetime.fromisoformat(target_origin.replace("Z", "+00:00")),
                end=datetime.fromisoformat(target_origin.replace("Z", "+00:00")),
                limit=250
            )
            self.active_demand_map = {r["h3_cell"]: float(r["predicted_rides"]) for r in fc_records}
        except Exception:
            self.active_demand_map = {}

    def _emit_event(
        self,
        event_type: str,
        message: str,
        driver_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        zone_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Emits an authoritative simulation operational event."""
        event = {
            "event_id": f"EVT-{self.clock_tick:04d}-{len(self.events) + 1:03d}",
            "event_type": event_type,
            "sim_time": self.current_sim_time.isoformat(),
            "message": message,
            "clock_tick": self.clock_tick,
            "driver_id": driver_id,
            "trip_id": trip_id,
            "zone_id": zone_id,
            "source_type": "SIMULATED"
        }
        self.events.append(event)
        if len(self.events) > 200:
            self.events = self.events[-200:]
        return event

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the most recent authoritative operational events."""
        return self.events[-limit:]

    def _load_zone_cache(self):
        """Loads H3 zone centroids and labels from zoneCatalog.json."""
        catalog_path = Path("frontend/src/services/zoneCatalog.json")
        if catalog_path.exists():
            with open(catalog_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
                for cell, data in catalog.items():
                    self.zone_coords[cell] = {
                        "lat": data["lat"],
                        "lng": data["lng"],
                        "label": data.get("label", f"Zone {cell[:8]}")
                    }
        else:
            # Fallback if catalog not present
            df_universe_path = Path("data/processed/zone_universe/zone_universe.parquet")
            if df_universe_path.exists():
                import pandas as pd
                df = pd.read_parquet(df_universe_path)
                for cell in df["h3_cell"].unique():
                    lat, lng = h3.cell_to_latlng(cell)
                    self.zone_coords[cell] = {"lat": lat, "lng": lng, "label": f"Zone {cell[:8]}"}

        # Filter operational zones to the validated operational universe
        df_universe_path = Path("data/processed/zone_universe/zone_universe.parquet")
        if df_universe_path.exists():
            try:
                import pandas as pd
                df_u = pd.read_parquet(df_universe_path)
                if "is_operational_universe" in df_u.columns:
                    op_cells = set(df_u[df_u["is_operational_universe"] == True]["h3_cell"])
                    valid_op = [c for c in op_cells if c in self.zone_coords]
                    if valid_op:
                        self.operational_zones = sorted(valid_op)
                    else:
                        self.operational_zones = sorted(list(self.zone_coords.keys()))
                else:
                    self.operational_zones = sorted(list(self.zone_coords.keys()))
            except Exception:
                self.operational_zones = sorted(list(self.zone_coords.keys()))
        else:
            self.operational_zones = sorted(list(self.zone_coords.keys()))

    def reset(self, origin_str: Optional[str] = None):
        """Resets simulation to deterministic initial state."""
        if origin_str:
            self.forecast_origin_str = origin_str
        self.load_demand_snapshot(self.forecast_origin_str)
        self.clock_tick = 0
        self.current_sim_time = self.sim_start_time
        self.drivers.clear()
        self.trips.clear()
        self.completed_trips.clear()
        self.events.clear()

        # Seeded deterministic distribution across valid operational zones
        rng = random.Random(self.seed)

        # Distribute 60 vehicles across 35 distinct staging hubs from operational zones:
        # 25 hubs get 2 vehicles, 10 hubs get 1 vehicle (25*2 + 10 = 60).
        # This guarantees low-demand zones hold genuine surplus V - ceil(D/2.0) >= 1,
        # allowing demand-aware dispatch across concentric H3 rings without violating coverage floors.
        num_staging = min(35, len(self.operational_zones))
        staging_zones = rng.sample(self.operational_zones, num_staging)

        driver_allocations = []
        double_count = min(25, self.fleet_size - num_staging)
        for z in staging_zones[:double_count]:
            driver_allocations.extend([z, z])
        for z in staging_zones[double_count:num_staging]:
            driver_allocations.append(z)
        while len(driver_allocations) < self.fleet_size:
            driver_allocations.append(rng.choice(staging_zones))

        for i in range(1, self.fleet_size + 1):
            d_id = f"DRV-{i:03d}"
            home_zone = driver_allocations[i - 1]
            coords = self.zone_coords[home_zone]

            # Realistic geographic micro-jitter strictly validated within H3 cell boundary
            # Guaranteed never to be placed in water or outside the supported service area
            valid_lat, valid_lng = coords["lat"], coords["lng"]
            for _ in range(15):
                j_lat = coords["lat"] + rng.uniform(-0.0018, 0.0018)
                j_lng = coords["lng"] + rng.uniform(-0.0018, 0.0018)
                try:
                    if h3.latlng_to_cell(j_lat, j_lng, 8) == home_zone:
                        valid_lat, valid_lng = j_lat, j_lng
                        break
                except Exception:
                    pass

            self.drivers[d_id] = {
                "driver_id": d_id,
                "name": f"Driver {i}",
                "status": "IDLE",  # IDLE, REPOSITIONING, TO_PICKUP, WITH_PASSENGER, OFF_DUTY
                "lat": round(valid_lat, 6),
                "lng": round(valid_lng, 6),
                "current_h3_cell": home_zone,
                "destination_h3_cell": None,
                "target_lat": None,
                "target_lng": None,
                "origin_lat": None,
                "origin_lng": None,
                "assigned_customer_id": None,
                "route_progress": 0.0,
                "eta_seconds": 0,
                "speed_kmh": 32.0,  # Average urban Chicago commercial speed
                "reposition_cooldown_ticks": 0,
                "completed_trips_count": 0,
                "source_type": "SIMULATED"
            }

    # --------------------------------------------------------------------------
    # Supply Accounting & Fleet Conservation
    # --------------------------------------------------------------------------

    def get_fleet_summary(self) -> Dict[str, int]:
        """Calculates instantaneous fleet counts across all states."""
        counts = {
            "total_drivers": len(self.drivers),
            "idle_count": 0,
            "repositioning_count": 0,
            "to_pickup_count": 0,
            "with_passenger_count": 0,
            "off_duty_count": 0
        }
        for d in self.drivers.values():
            st = d["status"]
            if st == "IDLE":
                counts["idle_count"] += 1
            elif st == "REPOSITIONING":
                counts["repositioning_count"] += 1
            elif st == "TO_PICKUP":
                counts["to_pickup_count"] += 1
            elif st == "WITH_PASSENGER":
                counts["with_passenger_count"] += 1
            elif st == "OFF_DUTY":
                counts["off_duty_count"] += 1

        # Assert strict fleet conservation
        sum_states = (
            counts["idle_count"] +
            counts["repositioning_count"] +
            counts["to_pickup_count"] +
            counts["with_passenger_count"] +
            counts["off_duty_count"]
        )
        assert sum_states == self.fleet_size, f"Fleet conservation violated: {sum_states} != {self.fleet_size}"
        return counts

    def get_zone_supply_accounting(self, demand_dict: Optional[Dict[str, float]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Calculates authoritative zone-level supply and pressure.
        A driver counts as available in zone z ONLY when status == IDLE and current_h3_cell == z.
        Drivers in-transit (REPOSITIONING, TO_PICKUP, WITH_PASSENGER) are strictly excluded from available supply.
        """
        active_demand = demand_dict if (demand_dict and len(demand_dict) > 0) else self.active_demand_map
        accounting: Dict[str, Dict[str, Any]] = {}
        for z in self.operational_zones:
            d_val = round(active_demand.get(z, 0.0), 4) if active_demand else 0.0
            accounting[z] = {
                "h3_cell": z,
                "available_vehicles_V": 0,
                "repositioning_incoming": 0,
                "occupied_vehicles": 0,
                "estimated_capacity_C": 0.0,
                "predicted_demand_D": d_val,
                "estimated_unserved_demand": 0.0,
                "pressure_level": "LOW",
                "pressure_status": "NORMAL"
            }

        # Tabulate driver states
        for d in self.drivers.values():
            st = d["status"]
            cur_z = d["current_h3_cell"]
            dest_z = d.get("destination_h3_cell")

            if st == "IDLE" and cur_z in accounting:
                accounting[cur_z]["available_vehicles_V"] += 1
            elif st == "REPOSITIONING" and dest_z in accounting:
                accounting[dest_z]["repositioning_incoming"] += 1
            elif st in {"TO_PICKUP", "WITH_PASSENGER"} and cur_z in accounting:
                accounting[cur_z]["occupied_vehicles"] += 1

        # Derive capacity and pressure per zone
        for z, row in accounting.items():
            # Standard RideIntel rate: r = 2.0 rides/vehicle per 30 minutes
            v = row["available_vehicles_V"]
            c = round(v * 2.0, 1)
            row["estimated_capacity_C"] = c
            d = row["predicted_demand_D"]
            shortage = round(max(0.0, d - c), 2)
            row["estimated_unserved_demand"] = shortage

            if c == 0.0 and d > 0.0:
                row["pressure_level"] = "NO_CAPACITY"
                row["pressure_status"] = "NO_ESTIMATED_CAPACITY"
            elif c == 0.0 and d == 0.0:
                row["pressure_level"] = "LOW"
                row["pressure_status"] = "NORMAL"
            else:
                ratio = d / c
                if ratio < 0.8:
                    row["pressure_level"] = "LOW"
                    row["pressure_status"] = "NORMAL"
                elif ratio <= 1.0:
                    row["pressure_level"] = "MODERATE"
                    row["pressure_status"] = "ELEVATED"
                elif ratio < 1.2:
                    row["pressure_level"] = "HIGH"
                    row["pressure_status"] = "HIGH_PRESSURE"
                else:
                    row["pressure_level"] = "CRITICAL"
                    row["pressure_status"] = "HIGH_PRESSURE"

        return accounting

    # --------------------------------------------------------------------------
    # Authoritative Dispatch Algorithm
    # --------------------------------------------------------------------------

    def dispatch(
        self,
        artifact_service: ArtifactService,
        origin_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Runs demand-aware dispatch logic:
        1. Evaluates all eligible idle drivers (cooldown == 0).
        2. Identifies deficit hotspot zones (D_z - C_z >= 0.5) from authoritative XGBoost forecast.
        3. Sorts targets by urgency: CRITICAL first, then HIGH; tie-breaker: largest deficit descending;
           secondary tie-breaker: h3_cell ascending for deterministic reproducibility.
        4. Matches targets with candidate donor zones in concentric H3 rings (Ring 1 -> 2 -> 3).
           Eligible donors must have pressure strictly LOW or MODERATE, surplus V - ceil(D/2.0) >= 1,
           and satisfy retained coverage floor: (V - 1) * 2.0 >= D.
        5. Preserves dispatch isolation: unassigned drivers remain unchanged.
        6. Respects per-destination limit (max 2 incoming) and global limit (10 assignments).
        7. Populates structured reason codes and explanatory summary.
        """
        target_origin = origin_str or self.forecast_origin_str

        # 1. Fetch real forecast snapshot from artifact service
        try:
            total_fc, fc_records = artifact_service.get_forecasts(
                model="xgboost",
                start=datetime.fromisoformat(target_origin.replace("Z", "+00:00")),
                end=datetime.fromisoformat(target_origin.replace("Z", "+00:00")),
                limit=150
            )
            demand_map = {r["h3_cell"]: float(r["predicted_rides"]) for r in fc_records}
            if demand_map:
                self.active_demand_map = demand_map
        except Exception:
            demand_map = self.active_demand_map or {}

        zone_supply = self.get_zone_supply_accounting(demand_map)

        # 2. Identify candidate idle drivers and group by origin cell
        zone_idle_drivers: Dict[str, List[Dict[str, Any]]] = {}
        for d in self.drivers.values():
            if d["status"] == "IDLE" and d["reposition_cooldown_ticks"] == 0:
                cur_z = d["current_h3_cell"]
                if cur_z not in zone_idle_drivers:
                    zone_idle_drivers[cur_z] = []
                zone_idle_drivers[cur_z].append(d)

        drivers_evaluated = sum(len(lst) for lst in zone_idle_drivers.values())

        # 3. Identify and sort deficit hotspots
        deficit_targets = []
        for z, data in zone_supply.items():
            deficit = data["predicted_demand_D"] - data["estimated_capacity_C"]
            if deficit >= 0.5:
                # Urgency: CRITICAL/NO_CAPACITY is tier 0, HIGH is tier 1
                urgency = 0 if data["pressure_level"] in ("CRITICAL", "NO_CAPACITY") else 1
                deficit_targets.append({
                    "h3_cell": z,
                    "urgency": urgency,
                    "deficit": deficit,
                    "demand": data["predicted_demand_D"],
                    "capacity": data["estimated_capacity_C"],
                    "incoming": data["repositioning_incoming"]
                })

        # Deterministic sorting: urgency asc (CRITICAL first), deficit desc, h3_cell asc
        deficit_targets.sort(key=lambda x: (x["urgency"], -x["deficit"], x["h3_cell"]))
        deficit_hotspots_before = len(deficit_targets)

        # Local accounting tracking for dispatch loop
        donor_avail_v: Dict[str, int] = {
            z: data["available_vehicles_V"] for z, data in zone_supply.items()
        }
        target_incoming: Dict[str, int] = {
            z: data["repositioning_incoming"] for z, data in zone_supply.items()
        }

        assignments = []
        skipped_reasons: Dict[str, int] = {}
        limit_reached = False
        max_global_assignments = 10
        max_incoming_per_dest = 2

        # Helper to compute donor pressure dynamically
        def _get_pressure(v: int, d: float) -> str:
            c = v * 2.0
            if c == 0.0 and d > 0.0:
                return "NO_CAPACITY"
            if c == 0.0 and d == 0.0:
                return "LOW"
            ratio = d / c
            if ratio < 0.8:
                return "LOW"
            elif ratio <= 1.0:
                return "MODERATE"
            elif ratio < 1.2:
                return "HIGH"
            return "CRITICAL"

        for hotspot in deficit_targets:
            if len(assignments) >= max_global_assignments:
                limit_reached = True
                break

            target_cell = hotspot["h3_cell"]
            target_coords = self.zone_coords.get(target_cell)
            if not target_coords:
                continue

            current_inc = target_incoming.get(target_cell, 0)
            needed = min(max_incoming_per_dest, math.ceil(hotspot["deficit"] / 2.0)) - current_inc
            if needed <= 0:
                skipped_reasons["DESTINATION_CAP_REACHED"] = skipped_reasons.get("DESTINATION_CAP_REACHED", 0) + 1
                continue

            # Concentric ring search: Ring 1 -> Ring 2 -> Ring 3
            matched_donor_info = None
            for r in [1, 2, 3]:
                disk_r = set(h3.grid_disk(target_cell, r))
                disk_prev = set(h3.grid_disk(target_cell, r - 1)) if r > 1 else {target_cell}
                ring_cells = (disk_r - disk_prev) & set(self.operational_zones)

                ring_candidates = []
                for d_cell in ring_cells:
                    d_drivers = zone_idle_drivers.get(d_cell, [])
                    if not d_drivers:
                        continue
                    v_cur = donor_avail_v.get(d_cell, 0)
                    if v_cur < 1:
                        continue
                    d_demand = zone_supply.get(d_cell, {}).get("predicted_demand_D", 0.0)

                    # Strict donor eligibility rules:
                    # 1. Donor pressure must be strictly LOW or MODERATE
                    p_lvl = _get_pressure(v_cur, d_demand)
                    if p_lvl not in ("LOW", "MODERATE"):
                        continue
                    # 2. Donor surplus check: V - ceil(D / 2.0) >= 1
                    if (v_cur - math.ceil(d_demand / 2.0)) < 1:
                        continue
                    # 3. Retained coverage floor: remaining vehicles must cover demand
                    if ((v_cur - 1) * 2.0) < d_demand:
                        continue

                    d_coords = self.zone_coords.get(d_cell)
                    if not d_coords:
                        continue
                    # Candidate idle driver with shortest distance
                    best_cand_drv = min(
                        d_drivers,
                        key=lambda d: haversine_km(d["lat"], d["lng"], target_coords["lat"], target_coords["lng"])
                    )
                    dist = haversine_km(best_cand_drv["lat"], best_cand_drv["lng"], target_coords["lat"], target_coords["lng"])
                    ring_candidates.append((dist, r, d_cell, best_cand_drv))

                if ring_candidates:
                    # Sort candidates by distance ascending, then cell ascending
                    ring_candidates.sort(key=lambda x: (x[0], x[2]))
                    matched_donor_info = ring_candidates[0]
                    break  # Found best donor in nearest ring!

            if matched_donor_info:
                dist, ring_num, d_cell, driver = matched_donor_info
                # Execute assignment
                zone_idle_drivers[d_cell].remove(driver)
                donor_avail_v[d_cell] -= 1
                target_incoming[target_cell] = target_incoming.get(target_cell, 0) + 1

                travel_seconds = int((dist / driver["speed_kmh"]) * 3600)
                driver["status"] = "REPOSITIONING"
                driver["destination_h3_cell"] = target_cell
                driver["origin_lat"] = driver["lat"]
                driver["origin_lng"] = driver["lng"]
                driver["target_lat"] = target_coords["lat"]
                driver["target_lng"] = target_coords["lng"]
                driver["route_progress"] = 0.0
                driver["eta_seconds"] = max(30, travel_seconds)
                driver["reposition_cooldown_ticks"] = 6
                driver["last_dispatched_at"] = self.current_sim_time.isoformat()

                dest_raw = self.zone_coords.get(target_cell, {}).get("label", target_cell[:8])
                dest_label = dest_raw if dest_raw.startswith("Zone") else f"Zone {dest_raw}"
                self._emit_event(
                    "DISPATCH_ASSIGNED",
                    f"Rider {driver['driver_id']} alerted — {dest_label} — forecast shortage detected — destination assigned.",
                    driver_id=driver["driver_id"],
                    zone_id=target_cell
                )
                assignments.append({
                    "driver_id": driver["driver_id"],
                    "origin_zone": d_cell,
                    "destination_zone": target_cell,
                    "ring": ring_num,
                    "distance_km": round(dist, 2),
                    "eta_seconds": driver["eta_seconds"],
                    "target_demand": round(hotspot["demand"], 2),
                    "target_deficit": round(hotspot["deficit"], 2)
                })
            else:
                skipped_reasons["NO_SURPLUS_DONOR_WITHIN_RADIUS"] = skipped_reasons.get("NO_SURPLUS_DONOR_WITHIN_RADIUS", 0) + 1

        dispatched_count = len(assignments)
        retained_for_coverage = max(0, drivers_evaluated - dispatched_count)

        # Recalculate remaining deficit hotspots
        post_supply = self.get_zone_supply_accounting(demand_map)
        deficit_hotspots_after = sum(
            1 for d in post_supply.values()
            if (d["predicted_demand_D"] - (d["estimated_capacity_C"] + d["repositioning_incoming"] * 2.0)) >= 0.5
        )

        if dispatched_count > 0:
            explanation = (
                f"Dispatched {dispatched_count} surplus vehicles across H3 Rings 1–3 to mitigate demand deficits "
                f"while retaining coverage across all donor zones. {deficit_hotspots_before - deficit_hotspots_after} "
                f"hotspots relieved."
            )
        else:
            reasons_summary = ", ".join(f"{k}: {v}" for k, v in skipped_reasons.items()) if skipped_reasons else "no deficit hotspots"
            explanation = f"0 vehicles dispatched ({reasons_summary}). Origin coverage floors maintained."

        return {
            "forecast_origin": target_origin,
            "prediction_horizon": "30 minutes",
            "drivers_considered": drivers_evaluated,
            "drivers_assigned": dispatched_count,
            "drivers_retained_coverage": retained_for_coverage,
            "underserved_zones_before": deficit_hotspots_before,
            "underserved_zones_after": deficit_hotspots_after,
            "assignments": assignments,
            "fleet_summary": self.get_fleet_summary(),
            "drivers_evaluated": drivers_evaluated,
            "dispatched_count": dispatched_count,
            "retained_for_coverage": retained_for_coverage,
            "target_zones_considered": len(deficit_targets),
            "skipped_reasons": skipped_reasons,
            "deficit_hotspots_before": deficit_hotspots_before,
            "deficit_hotspots_after": deficit_hotspots_after,
            "limit_reached": limit_reached,
            "explanation": explanation
        }

    # --------------------------------------------------------------------------
    # Simulation Step & Kinematics
    # --------------------------------------------------------------------------

    def step(self, seconds: int = 30) -> Dict[str, Any]:
        """
        Advances the simulation clock by specified seconds:
        - Updates in-transit drivers along deterministic interpolated trajectories.
        - Handles arrivals:
            * REPOSITIONING -> IDLE at destination zone.
            * TO_PICKUP -> WITH_PASSENGER, trip status ON_TRIP.
            * WITH_PASSENGER -> IDLE, trip status COMPLETED.
        - Decrements oscillation cooldown ticks.
        """
        self.clock_tick += 1
        self.current_sim_time += timedelta(seconds=seconds)

        for d in self.drivers.values():
            st = d["status"]

            # Cooldown decrement for idle drivers
            if st == "IDLE" and d["reposition_cooldown_ticks"] > 0:
                d["reposition_cooldown_ticks"] -= 1

            if st in {"REPOSITIONING", "TO_PICKUP", "WITH_PASSENGER"}:
                t_lat = d["target_lat"]
                t_lng = d["target_lng"]
                o_lat = d["origin_lat"] or d["lat"]
                o_lng = d["origin_lng"] or d["lng"]

                if t_lat is None or t_lng is None:
                    continue

                total_dist = haversine_km(o_lat, o_lng, t_lat, t_lng)
                if total_dist <= 0.01:
                    step_pct = 1.0
                else:
                    dist_moved = (d["speed_kmh"] * (seconds / 3600.0))
                    step_pct = dist_moved / total_dist

                d["route_progress"] = min(1.0, d["route_progress"] + step_pct)
                prog = d["route_progress"]

                # Interpolate spatial coordinates along linear trajectory
                d["lat"] = round(o_lat + (t_lat - o_lat) * prog, 6)
                d["lng"] = round(o_lng + (t_lng - o_lng) * prog, 6)
                rem_dist = max(0.0, total_dist * (1.0 - prog))
                d["eta_seconds"] = max(0, int((rem_dist / d["speed_kmh"]) * 3600))

                # Handle Arrival
                if d["route_progress"] >= 1.0:
                    d["lat"] = t_lat
                    d["lng"] = t_lng
                    d["route_progress"] = 0.0
                    d["eta_seconds"] = 0

                    if st == "REPOSITIONING":
                        # Arrived at destination zone
                        dest_zone = d["destination_h3_cell"]
                        d["status"] = "IDLE"
                        d["current_h3_cell"] = dest_zone
                        d["destination_h3_cell"] = None
                        d["target_lat"] = None
                        d["target_lng"] = None
                        d["origin_lat"] = None
                        d["origin_lng"] = None
                        dest_raw = self.zone_coords.get(dest_zone, {}).get("label", dest_zone[:8])
                        dest_label = dest_raw if dest_raw.startswith("Zone") else f"Zone {dest_raw}"
                        self._emit_event(
                            "REPOSITIONING_ARRIVED",
                            f"Rider {d['driver_id']} reached demand hotspot {dest_label}.",
                            driver_id=d["driver_id"],
                            zone_id=dest_zone
                        )

                    elif st == "TO_PICKUP":
                        # Arrived at customer pickup location!
                        cust_id = d.get("assigned_customer_id")
                        trip = self.trips.get(cust_id)
                        if trip and trip["status"] == "ASSIGNED":
                            trip["status"] = "ON_TRIP"
                            trip["pickup_at"] = self.current_sim_time.isoformat()

                            # Transition driver to passenger leg
                            d["status"] = "WITH_PASSENGER"
                            d["destination_h3_cell"] = trip["dropoff_h3_cell"]
                            d["origin_lat"] = d["lat"]
                            d["origin_lng"] = d["lng"]
                            d["target_lat"] = trip["dropoff_lat"]
                            d["target_lng"] = trip["dropoff_lng"]
                            dropoff_dist = haversine_km(d["lat"], d["lng"], trip["dropoff_lat"], trip["dropoff_lng"])
                            d["eta_seconds"] = max(30, int((dropoff_dist / d["speed_kmh"]) * 3600))
                            self._emit_event(
                                "PICKUP_COMPLETED",
                                f"Rider {d['driver_id']} picked up passenger for ride {cust_id}.",
                                driver_id=d["driver_id"],
                                trip_id=cust_id,
                                zone_id=trip.get("pickup_h3_cell")
                            )
                        else:
                            d["status"] = "IDLE"
                            d["destination_h3_cell"] = None
                            d["target_lat"] = None
                            d["target_lng"] = None
                            d["origin_lat"] = None
                            d["origin_lng"] = None
                            d["assigned_customer_id"] = None

                    elif st == "WITH_PASSENGER":
                        # Arrived at customer dropoff destination!
                        cust_id = d.get("assigned_customer_id")
                        trip = self.trips.get(cust_id)
                        dropoff_zone = d["destination_h3_cell"]

                        d["status"] = "IDLE"
                        d["current_h3_cell"] = dropoff_zone
                        d["destination_h3_cell"] = None
                        d["target_lat"] = None
                        d["target_lng"] = None
                        d["origin_lat"] = None
                        d["origin_lng"] = None
                        d["assigned_customer_id"] = None
                        d["completed_trips_count"] += 1
                        d["reposition_cooldown_ticks"] = 0  # Immediately eligible for next dispatch cycle

                        if trip:
                            trip["status"] = "COMPLETED"
                            trip["completed_at"] = self.current_sim_time.isoformat()
                            self.completed_trips.append(trip)
                            del self.trips[cust_id]

                        drop_label = self.zone_coords.get(dropoff_zone, {}).get("label", dropoff_zone[:8])
                        self._emit_event(
                            "TRIP_COMPLETED",
                            f"Ride {cust_id} completed by rider {d['driver_id']} at Zone {drop_label}.",
                            driver_id=d["driver_id"],
                            trip_id=cust_id,
                            zone_id=dropoff_zone
                        )

        return self.get_state()

    # --------------------------------------------------------------------------
    # Customer Trip Lifecycle
    # --------------------------------------------------------------------------

    def create_customer_request(
        self,
        pickup_h3_cell: str,
        dropoff_h3_cell: str,
        pickup_lat: Optional[float] = None,
        pickup_lng: Optional[float] = None,
        dropoff_lat: Optional[float] = None,
        dropoff_lng: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Creates a simulated customer ride request:
        1. Validates pickup and dropoff zones.
        2. Finds closest eligible IDLE driver.
        3. If found, transitions driver to TO_PICKUP and trip to ASSIGNED.
        4. If none available, retains trip as REQUESTED (unserved).
        """
        if pickup_h3_cell not in self.zone_coords:
            raise ValueError(f"Pickup zone '{pickup_h3_cell}' is not a valid catalog zone.")
        if dropoff_h3_cell not in self.zone_coords:
            raise ValueError(f"Dropoff zone '{dropoff_h3_cell}' is not a valid catalog zone.")

        p_coords = self.zone_coords[pickup_h3_cell]
        d_coords = self.zone_coords[dropoff_h3_cell]

        plat = pickup_lat or p_coords["lat"]
        plng = pickup_lng or p_coords["lng"]
        dlat = dropoff_lat or d_coords["lat"]
        dlng = dropoff_lng or d_coords["lng"]

        dist_km = max(0.5, round(haversine_km(plat, plng, dlat, dlng), 2))
        fare = round(3.25 + 1.80 * dist_km, 2)  # Chicago standard taxi base + mileage

        req_id = f"REQ-{self.clock_tick:04d}-{len(self.trips) + len(self.completed_trips) + 1:03d}"

        trip = {
            "request_id": req_id,
            "pickup_lat": plat,
            "pickup_lng": plng,
            "pickup_h3_cell": pickup_h3_cell,
            "dropoff_lat": dlat,
            "dropoff_lng": dlng,
            "dropoff_h3_cell": dropoff_h3_cell,
            "status": "REQUESTED",
            "assigned_driver_id": None,
            "created_at": self.current_sim_time.isoformat(),
            "pickup_at": None,
            "completed_at": None,
            "distance_km": dist_km,
            "fare_estimate": fare,
            "source_type": "SIMULATED"
        }

        # Match closest IDLE driver
        best_driver = None
        best_dist = float("inf")

        for d in self.drivers.values():
            if d["status"] == "IDLE":
                dist = haversine_km(d["lat"], d["lng"], plat, plng)
                if dist < best_dist and dist <= 12.0:  # 12km max pickup radius
                    best_dist = dist
                    best_driver = d

        if best_driver:
            # Assign driver
            trip["status"] = "ASSIGNED"
            trip["assigned_driver_id"] = best_driver["driver_id"]

            pickup_travel_sec = int((best_dist / best_driver["speed_kmh"]) * 3600)
            best_driver["status"] = "TO_PICKUP"
            best_driver["assigned_customer_id"] = req_id
            best_driver["destination_h3_cell"] = pickup_h3_cell
            best_driver["origin_lat"] = best_driver["lat"]
            best_driver["origin_lng"] = best_driver["lng"]
            best_driver["target_lat"] = plat
            best_driver["target_lng"] = plng
            best_driver["route_progress"] = 0.0
            best_driver["eta_seconds"] = max(20, pickup_travel_sec)

            self._emit_event(
                "DRIVER_ASSIGNED",
                f"Rider {best_driver['driver_id']} assigned to customer ride {req_id} (ETA: {best_driver['eta_seconds']}s).",
                driver_id=best_driver["driver_id"],
                trip_id=req_id,
                zone_id=pickup_h3_cell
            )
        else:
            self._emit_event(
                "REQUEST_QUEUED",
                f"Ride request {req_id} queued — no available idle driver within 12km.",
                trip_id=req_id,
                zone_id=pickup_h3_cell
            )

        self.trips[req_id] = trip
        return trip

    def cancel_customer_request(self, request_id: str) -> Dict[str, Any]:
        """Cancels an active customer request and safely restores assigned driver to IDLE."""
        if request_id not in self.trips:
            raise KeyError(f"Customer request '{request_id}' not found in active trips.")

        trip = self.trips[request_id]
        if trip["status"] not in {"REQUESTED", "ASSIGNED"}:
            raise ValueError(f"Cannot cancel trip with status '{trip['status']}' (already in progress).")

        d_id = trip.get("assigned_driver_id")
        if d_id and d_id in self.drivers:
            driver = self.drivers[d_id]
            # Safely restore driver to IDLE at their current intermediate location
            driver["status"] = "IDLE"
            driver["assigned_customer_id"] = None
            driver["destination_h3_cell"] = None
            driver["target_lat"] = None
            driver["target_lng"] = None
            driver["origin_lat"] = None
            driver["origin_lng"] = None
            driver["route_progress"] = 0.0
            driver["eta_seconds"] = 0

        trip["status"] = "CANCELLED"
        cancelled_trip = trip.copy()
        del self.trips[request_id]

        self._emit_event(
            "TRIP_CANCELLED",
            f"Customer ride {request_id} cancelled. Assigned driver {d_id or 'none'} restored to IDLE.",
            driver_id=d_id,
            trip_id=request_id
        )
        return cancelled_trip

    # --------------------------------------------------------------------------
    # Full State Query
    # --------------------------------------------------------------------------

    def get_state(self, demand_dict: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Assembles authoritative simulation snapshot."""
        return {
            "simulation_time": self.current_sim_time.isoformat(),
            "clock_tick": self.clock_tick,
            "forecast_origin": self.forecast_origin_str,
            "prediction_horizon": "30 minutes",
            "fleet_summary": self.get_fleet_summary(),
            "drivers": list(self.drivers.values()),
            "active_trips": list(self.trips.values()),
            "completed_trips_count": len(self.completed_trips),
            "zone_supply": self.get_zone_supply_accounting(demand_dict),
            "recent_events": self.events[-20:],
            "current_sim_time": self.current_sim_time.isoformat()
        }


# Singleton engine instance
simulation_engine = FleetSimulationEngine(fleet_size=60, seed=42)

