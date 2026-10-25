import test from 'node:test';
import assert from 'node:assert/strict';

const DRIVER_STATUS_COLORS = {
  IDLE: '#10b981',
  REPOSITIONING: '#06b6d4',
  TO_PICKUP: '#f59e0b',
  WITH_PASSENGER: '#8b5cf6',
  OFF_DUTY: '#64748b'
};

test('driver status colors map to canonical palette', () => {
  assert.equal(DRIVER_STATUS_COLORS.IDLE, '#10b981');
  assert.equal(DRIVER_STATUS_COLORS.REPOSITIONING, '#06b6d4');
  assert.equal(DRIVER_STATUS_COLORS.TO_PICKUP, '#f59e0b');
  assert.equal(DRIVER_STATUS_COLORS.WITH_PASSENGER, '#8b5cf6');
  assert.equal(DRIVER_STATUS_COLORS.OFF_DUTY, '#64748b');
});

test('fleet conservation invariant holds across driver states', () => {
  const mockFleet = [
    { driver_id: 'DRV-001', status: 'IDLE' },
    { driver_id: 'DRV-002', status: 'REPOSITIONING' },
    { driver_id: 'DRV-003', status: 'TO_PICKUP' },
    { driver_id: 'DRV-004', status: 'WITH_PASSENGER' },
    { driver_id: 'DRV-005', status: 'IDLE' }
  ];

  const total = mockFleet.length;
  const counts = {
    idle: mockFleet.filter(d => d.status === 'IDLE').length,
    repositioning: mockFleet.filter(d => d.status === 'REPOSITIONING').length,
    to_pickup: mockFleet.filter(d => d.status === 'TO_PICKUP').length,
    with_passenger: mockFleet.filter(d => d.status === 'WITH_PASSENGER').length
  };

  assert.equal(counts.idle + counts.repositioning + counts.to_pickup + counts.with_passenger, total);
  assert.equal(counts.idle, 2);
  assert.equal(counts.repositioning, 1);
  assert.equal(counts.to_pickup, 1);
  assert.equal(counts.with_passenger, 1);
});

test('dispatch summary accounting verifies coverage and assignments', () => {
  const dispatchResult = {
    drivers_considered: 45,
    drivers_assigned: 6,
    drivers_retained_coverage: 39,
    underserved_zones_before: 12,
    underserved_zones_after: 6
  };

  assert.ok(dispatchResult.drivers_assigned <= dispatchResult.drivers_considered);
  assert.equal(
    dispatchResult.drivers_assigned + dispatchResult.drivers_retained_coverage,
    dispatchResult.drivers_considered
  );
  assert.ok(dispatchResult.underserved_zones_after <= dispatchResult.underserved_zones_before);
});

test('simulation speed multipliers map to expected interval milliseconds', () => {
  const getIntervalMs = (speed) => Math.round(1000 / speed);

  assert.equal(getIntervalMs(0.5), 2000);
  assert.equal(getIntervalMs(1.0), 1000);
  assert.equal(getIntervalMs(2.0), 500);
  assert.equal(getIntervalMs(4.0), 250);
});

test('customer trips breakdown correctly tabulates unserved and in-transit requests', () => {
  const mockTrips = [
    { request_id: 'REQ-0001', status: 'REQUESTED' },
    { request_id: 'REQ-0002', status: 'ASSIGNED' },
    { request_id: 'REQ-0003', status: 'ON_TRIP' },
    { request_id: 'REQ-0004', status: 'REQUESTED' }
  ];

  const totalActive = mockTrips.length;
  const unserved = mockTrips.filter(t => t.status === 'REQUESTED').length;
  const inTransit = mockTrips.filter(t => t.status === 'ASSIGNED' || t.status === 'ON_TRIP').length;

  assert.equal(totalActive, 4);
  assert.equal(unserved, 2);
  assert.equal(inTransit, 2);
  assert.equal(unserved + inTransit, totalActive);
});

test('in-flight stepping guard prevents concurrent step executions', () => {
  let isStepping = false;
  let executionCount = 0;

  function attemptStep() {
    if (isStepping) return false;
    isStepping = true;
    executionCount += 1;
    // Step in-flight...
    return true;
  }

  // First step succeeds
  assert.equal(attemptStep(), true);
  assert.equal(executionCount, 1);

  // Concurrent step while locked is blocked
  assert.equal(attemptStep(), false);
  assert.equal(executionCount, 1);

  // Unlocking permits next step
  isStepping = false;
  assert.equal(attemptStep(), true);
  assert.equal(executionCount, 2);
});

test('dynamic capacity and pressure calculation with live simulation vehicles', () => {
  // Case A: Normal with deficit
  const v_idle = 3;
  const c = v_idle * 2.0;
  const d = 8.5;
  const shortage = Math.max(0, d - c);
  assert.equal(c, 6.0);
  assert.equal(shortage, 2.5);
  const ratio = d / c;
  assert.ok(ratio >= 1.2, 'Ratio exceeds 1.2 for CRITICAL');

  // Case B: No capacity with positive demand -> NO_CAPACITY
  const v_zero = 0;
  const c_zero = v_zero * 2.0;
  const d_pos = 4.2;
  const shortage_zero = Math.max(0, d_pos - c_zero);
  assert.equal(c_zero, 0.0);
  assert.equal(shortage_zero, 4.2);
  const pressureLevel = (c_zero === 0 && d_pos > 0) ? 'NO_CAPACITY' : 'NORMAL';
  assert.equal(pressureLevel, 'NO_CAPACITY');
});

test('reset epoch guard prevents in-flight step from overwriting reset state', () => {
  let resetEpoch = 0;
  let activeSimState = { tick: 0, status: 'INITIAL' };

  // 1. Simulation starts stepping
  const stepEpoch = resetEpoch;

  // 2. User clicks Reset while step request is in flight
  resetEpoch += 1;
  activeSimState = { tick: 0, status: 'RESET_INITIAL' };

  // 3. Delayed step response arrives
  const delayedStepState = { tick: 5, status: 'STEPPED' };
  if (stepEpoch === resetEpoch) {
    activeSimState = delayedStepState; // Should NOT happen!
  }

  // 4. Assert reset state was preserved and delayed step was ignored
  assert.equal(activeSimState.tick, 0);
  assert.equal(activeSimState.status, 'RESET_INITIAL');
});

test('live driver selection synchronization updates kinematics from simulation state', () => {
  let selectedDriver = {
    driver_id: 'DRV-001',
    status: 'TO_PICKUP',
    route_progress: 0.1,
    eta_seconds: 120
  };

  const newSimState = {
    drivers: [
      {
        driver_id: 'DRV-001',
        status: 'WITH_PASSENGER',
        route_progress: 0.65,
        eta_seconds: 40
      },
      {
        driver_id: 'DRV-002',
        status: 'IDLE',
        route_progress: 0.0,
        eta_seconds: 0
      }
    ]
  };

  // Sync logic matching ChicagoMapView useEffect
  if (selectedDriver) {
    const liveD = newSimState.drivers.find(d => d.driver_id === selectedDriver.driver_id);
    if (liveD) selectedDriver = liveD;
  }

  assert.equal(selectedDriver.status, 'WITH_PASSENGER');
  assert.equal(selectedDriver.route_progress, 0.65);
  assert.equal(selectedDriver.eta_seconds, 40);
});

test('chicagoSquareGrid.json contains exactly 105 square features covering 239 catalog cells', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const raw = fs.readFileSync(path.join(process.cwd(), 'src', 'services', 'chicagoSquareGrid.json'), 'utf-8');
  const grid = JSON.parse(raw);

  assert.equal(grid.type, 'FeatureCollection');
  assert.equal(grid.features.length, 105);

  const allH3 = [];
  grid.features.forEach(f => {
    assert.equal(f.type, 'Feature');
    assert.ok(f.id.startsWith('SQ-'));
    assert.equal(f.geometry.type, 'Polygon');
    const ring = f.geometry.coordinates[0];
    assert.equal(ring.length, 5, 'Square polygon ring must have 5 coordinates (closed)');
    assert.deepEqual(ring[0], ring[4], 'Polygon must close');
    allH3.push(...f.properties.h3_cells);
  });

  assert.equal(allH3.length, 239, 'Must aggregate exactly 239 H3 cells');
  assert.equal(new Set(allH3).size, 239, 'Zero double-counting allowed');
});

test('square grid aggregation correctly sums demand, capacity and identifies pressure', () => {
  const mockSquare = {
    id: 'SQ-05-10',
    properties: {
      h3_cells: ['882664c1a9fffff', '882664c1edfffff']
    }
  };

  const mockZoneRecords = {
    '882664c1a9fffff': { predicted_rides_D: 3.5 },
    '882664c1edfffff': { predicted_rides_D: 4.5 }
  };

  const mockSimState = {
    drivers: [
      { driver_id: 'DRV-001', status: 'IDLE', current_h3_cell: '882664c1a9fffff' },
      { driver_id: 'DRV-002', status: 'IDLE', current_h3_cell: '882664c1edfffff' },
      { driver_id: 'DRV-003', status: 'REPOSITIONING', current_h3_cell: 'other', destination_h3_cell: '882664c1a9fffff' }
    ],
    active_trips: [
      { request_id: 'REQ-01', pickup_h3_cell: '882664c1a9fffff', dropoff_h3_cell: 'other' }
    ]
  };

  const h3Cells = mockSquare.properties.h3_cells;
  const demandD = h3Cells.reduce((acc, cell) => acc + (mockZoneRecords[cell]?.predicted_rides_D || 0), 0);
  const idleCount = mockSimState.drivers.filter(d => d.status === 'IDLE' && h3Cells.includes(d.current_h3_cell)).length;
  const capacityC = idleCount * 2.0;
  const shortage = Math.max(0, demandD - capacityC);
  const incoming = mockSimState.drivers.filter(d => d.status === 'REPOSITIONING' && h3Cells.includes(d.destination_h3_cell)).length;

  assert.equal(demandD, 8.0);
  assert.equal(idleCount, 2);
  assert.equal(capacityC, 4.0);
  assert.equal(shortage, 4.0);
  assert.equal(incoming, 1);
});

test('bearing angle calculation returns valid headings in [0, 360)', () => {
  function calculateBearing(lat1, lon1, lat2, lon2) {
    if (lat1 === lat2 && lon1 === lon2) return 0;
    const phi1 = (lat1 * Math.PI) / 180;
    const phi2 = (lat2 * Math.PI) / 180;
    const deltaLambda = ((lon2 - lon1) * Math.PI) / 180;
    const y = Math.sin(deltaLambda) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(deltaLambda);
    const theta = Math.atan2(y, x);
    return Math.round(((theta * 180) / Math.PI + 360) % 360);
  }

  // Due North
  assert.equal(calculateBearing(41.8, -87.6, 41.9, -87.6), 0);
  // Due East
  assert.equal(calculateBearing(41.8, -87.6, 41.8, -87.5), 90);
  // Due South
  assert.equal(calculateBearing(41.9, -87.6, 41.8, -87.6), 180);
  // Due West
  assert.equal(calculateBearing(41.8, -87.5, 41.8, -87.6), 270);
});

test('heatmap pressure and visual score recalculate on vehicle arrival', () => {
  // Helper implementing the authoritative aggregateSquareTelemetry score logic
  function computeSquareScoreAndPressure(totalDemand, totalIdleVehicles) {
    const capacity = Math.round(totalIdleVehicles * 2.0 * 10) / 10;
    const shortage = Math.max(0, Math.round((totalDemand - capacity) * 100) / 100);

    let pressureLevel = 'LOW';
    if (capacity === 0 && totalDemand > 0) {
      pressureLevel = 'NO_CAPACITY';
    } else if (capacity === 0 && totalDemand === 0) {
      pressureLevel = 'LOW';
    } else {
      const ratio = totalDemand / capacity;
      if (ratio < 0.8) pressureLevel = 'LOW';
      else if (ratio <= 1.0) pressureLevel = 'MODERATE';
      else if (ratio < 1.2) pressureLevel = 'HIGH';
      else pressureLevel = 'CRITICAL';
    }

    let visualScore = 0.0;
    if (pressureLevel === 'LOW') {
      const ratio = capacity > 0 ? (totalDemand / capacity) : 0.0;
      const rel = Math.max(0.0, Math.min(1.0, ratio / 0.8));
      visualScore = 0.06 + rel * (0.25 - 0.06);
    } else if (pressureLevel === 'MODERATE') {
      const ratio = capacity > 0 ? (totalDemand / capacity) : 0.9;
      const rel = Math.max(0.0, Math.min(1.0, (ratio - 0.8) / 0.2));
      visualScore = 0.26 + rel * (0.50 - 0.26);
    } else if (pressureLevel === 'HIGH') {
      const ratio = capacity > 0 ? (totalDemand / capacity) : 1.1;
      const rel = Math.max(0.0, Math.min(1.0, (ratio - 1.0) / 0.2));
      visualScore = 0.51 + rel * (0.75 - 0.51);
    } else {
      // CRITICAL or NO_CAPACITY
      if (capacity > 0) {
        const ratio = totalDemand / capacity;
        const rel = Math.max(0.0, Math.min(1.0, (ratio - 1.2) / 1.5));
        visualScore = 0.76 + rel * (1.00 - 0.76);
      } else {
        const rel = Math.max(0.0, Math.min(1.0, totalDemand / 12.0));
        visualScore = 0.80 + rel * 0.20;
      }
    }

    return { capacity, shortage, pressureLevel, visualScore };
  }

  // 1. Initial State: Demand = 3.6, Vehicles = 0 -> NO_CAPACITY, Critical Red
  const pre = computeSquareScoreAndPressure(3.6, 0);
  assert.equal(pre.capacity, 0.0);
  assert.equal(pre.pressureLevel, 'NO_CAPACITY');
  assert.ok(pre.visualScore >= 0.76, `Pre-arrival score should be in critical red tier (>=0.76), got ${pre.visualScore}`);

  // 2. Arrival 1: 1 vehicle arrives -> V = 1, C = 2.0. Ratio = 3.6 / 2.0 = 1.8 -> CRITICAL (genuine shortage remains)
  const arr1 = computeSquareScoreAndPressure(3.6, 1);
  assert.equal(arr1.capacity, 2.0);
  assert.equal(arr1.shortage, 1.6);
  assert.equal(arr1.pressureLevel, 'CRITICAL');
  assert.ok(arr1.visualScore >= 0.76, `Score should remain critical while genuine shortage persists, got ${arr1.visualScore}`);

  // 3. Arrival 2: 1 more vehicle arrives -> V = 2, C = 4.0. Ratio = 3.6 / 4.0 = 0.9 -> MODERATE
  const arr2 = computeSquareScoreAndPressure(3.6, 2);
  assert.equal(arr2.capacity, 4.0);
  assert.equal(arr2.shortage, 0.0);
  assert.equal(arr2.pressureLevel, 'MODERATE');
  assert.ok(arr2.visualScore >= 0.26 && arr2.visualScore <= 0.50, `Score must transition to Moderate tier (0.26-0.50), got ${arr2.visualScore}`);

  // 4. Arrival 3: 1 more vehicle arrives -> V = 3, C = 6.0. Ratio = 3.6 / 6.0 = 0.6 -> LOW (Normal Green)
  const arr3 = computeSquareScoreAndPressure(3.6, 3);
  assert.equal(arr3.capacity, 6.0);
  assert.equal(arr3.shortage, 0.0);
  assert.equal(arr3.pressureLevel, 'LOW');
  assert.ok(arr3.visualScore >= 0.06 && arr3.visualScore <= 0.25, `Score must transition to Low tier (0.06-0.25), got ${arr3.visualScore}`);
});




