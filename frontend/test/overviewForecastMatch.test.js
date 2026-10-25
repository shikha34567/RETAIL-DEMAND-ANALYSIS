import test from 'node:test';
import assert from 'node:assert/strict';
import { getZoneLabel, getZoneDetails } from '../src/services/zoneLabels.js';

test('Overview chart data transformation preserves fractional predicted demand for Zone Z-005', () => {
  // Authoritative raw record returned by GET /api/v1/pressure for Zone Z-005 at 2022-06-22T05:00:00Z
  const fixturePressureRow = {
    h3_cell: '8826641b23fffff',
    forecast_origin: '2022-06-22T05:00:00Z',
    target_start: '2022-06-22T05:00:00Z',
    target_end: '2022-06-22T05:30:00Z',
    model_name: 'xgboost',
    capacity_rate_r: 2.0,
    forecast_demand_rides_30m: 0.3596688210964203,
    predicted_rides_D: 0.3596688210964203,
    simulated_available_vehicles: 0,
    available_vehicles_V: 0,
    estimated_supply_capacity_rides_30m: 0.0,
    estimated_capacity_C: 0.0,
    demand_supply_ratio: null,
    pressure_index: null,
    estimated_unserved_demand_rides: 0.3596688210964203,
    pressure_status: 'NO_ESTIMATED_CAPACITY',
    pressure_level: 'NO_CAPACITY',
    input_status: 'OK',
    supply_data_status: 'SIMULATED_ESTIMATE',
    is_potential_surge: false,
    surge_severity: 'NONE',
    surge_trigger_reason: 'DEMAND_BELOW_MINIMUM_THRESHOLD',
    source_type: 'ESTIMATED'
  };

  // Perform exact OverviewView.jsx transformation
  const zoneLabel = getZoneLabel(fixturePressureRow.h3_cell);
  const details = getZoneDetails(fixturePressureRow.h3_cell);
  const demand = Number((fixturePressureRow.predicted_rides_D || 0).toFixed(2));
  const capacity = Number((fixturePressureRow.estimated_capacity_C || 0).toFixed(1));
  const shortage = Number((fixturePressureRow.estimated_unserved_demand_rides || 0).toFixed(2));

  // Assert label matches canonical taxonomy
  assert.equal(zoneLabel, 'Zone Z-005');
  assert.equal(details.id, '8826641b23fffff');

  // Assert fractional demand is preserved at 2 decimal places and NOT rounded to zero
  assert.equal(demand, 0.36);
  assert.notEqual(demand, 0);

  // Assert estimated capacity is zero
  assert.equal(capacity, 0);

  // Assert expected shortage is identical to predicted demand when C = 0
  assert.equal(shortage, 0.36);

  // Assert tooltip string representations match exact user display
  const tooltipDemand = `${demand} rides`;
  const tooltipCapacity = `${capacity} rides (${fixturePressureRow.available_vehicles_V} veh)`;
  const tooltipShortage = `${shortage} rides`;

  assert.equal(tooltipDemand, '0.36 rides');
  assert.equal(tooltipCapacity, '0 rides (0 veh)');
  assert.equal(tooltipShortage, '0.36 rides');
});

test('Overview shortage sort correctly prioritizes NO_CAPACITY deficits over surplus zones', () => {
  // Snapshot with peripheral zero-capacity zone vs downtown high-capacity zone
  const mockSnapshot = [
    {
      h3_cell: '8827593433fffff', // Downtown zone: D = 39.32, C = 194.0 -> Shortage = 0
      predicted_rides_D: 39.321857,
      estimated_capacity_C: 194.0,
      estimated_unserved_demand_rides: 0.0,
      pressure_level: 'LOW'
    },
    {
      h3_cell: '8826641b23fffff', // Zone Z-005: D = 0.36, C = 0.0 -> Shortage = 0.36
      predicted_rides_D: 0.3596688,
      estimated_capacity_C: 0.0,
      estimated_unserved_demand_rides: 0.3596688,
      pressure_level: 'NO_CAPACITY'
    }
  ];

  const sorted = [...mockSnapshot].sort(
    (a, b) => (b.estimated_unserved_demand_rides || 0) - (a.estimated_unserved_demand_rides || 0)
  );

  assert.equal(sorted[0].h3_cell, '8826641b23fffff');
  assert.equal(getZoneLabel(sorted[0].h3_cell), 'Zone Z-005');
  assert.equal(sorted[1].h3_cell, '8827593433fffff');
});

