import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createDispatchToast,
  extractArrivalToasts,
  detectPressureTransitions
} from '../src/services/simulationNotifications.js';

test('createDispatchToast generates informative toast for positive assignments', () => {
  const dispatchRes = {
    drivers_assigned: 3,
    underserved_zones_before: 5,
    underserved_zones_after: 2,
    assignments: [
      { driver_id: 'DRV-001', target_zone_id: '882681a339fffff' },
      { driver_id: 'DRV-002', target_zone_id: '882681a339fffff' },
      { driver_id: 'DRV-003', target_zone_id: '882681a30bfffff' }
    ],
    skipped_reasons: {
      MINIMUM_ORIGIN_COVERAGE_RETAINED: 4
    }
  };

  const toast = createDispatchToast(dispatchRes);
  assert.ok(toast);
  assert.equal(toast.type, 'dispatch');
  assert.equal(toast.severity, 'info');
  assert.equal(toast.title, 'Status Update Completed');
  assert.ok(toast.message.includes('3 simulated riders dispatched toward'));
  assert.ok(toast.message.includes('Zone '));
});

test('createDispatchToast generates clear neutral toast for zero assignments with reasons', () => {
  const dispatchRes = {
    drivers_assigned: 0,
    drivers_considered: 12,
    drivers_retained_coverage: 12,
    underserved_zones_before: 4,
    underserved_zones_after: 4,
    skipped_reasons: {
      NO_SURPLUS_DONOR_WITHIN_RADIUS: 4
    }
  };

  const toast = createDispatchToast(dispatchRes);
  assert.ok(toast);
  assert.equal(toast.type, 'dispatch');
  assert.equal(toast.severity, 'neutral');
  assert.equal(toast.title, 'Status Update: 0 Dispatched');
  assert.ok(toast.message.includes('No surplus idle donors within search radius'));
});

test('createDispatchToast handles invalid or empty payload gracefully', () => {
  assert.equal(createDispatchToast(null), null);
  assert.equal(createDispatchToast(undefined), null);
  assert.equal(createDispatchToast({}), null);
});

test('extractArrivalToasts extracts single kinematic reposition arrival', () => {
  const seenEventIds = new Set();
  const events = [
    {
      event_id: 'EVT-0010-001',
      event_type: 'REPOSITIONING_ARRIVED',
      driver_id: 'DRV-042',
      zone_id: '882681a339fffff',
      sim_time: '2022-06-22T13:02:00Z',
      message: 'Vehicle DRV-042 arrived at destination 882681a339fffff and is now IDLE'
    }
  ];

  const toasts = extractArrivalToasts(events, seenEventIds);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].type, 'arrival');
  assert.equal(toasts[0].severity, 'info');
  assert.equal(toasts[0].title, 'Simulated Rider Arrived');
  assert.ok(toasts[0].message.includes('DRV-042'));
  assert.ok(toasts[0].message.includes('Zone '));
  assert.ok(seenEventIds.has('EVT-0010-001'));
});

test('extractArrivalToasts deduplicates previously seen event IDs', () => {
  const seenEventIds = new Set(['EVT-0010-001']);
  const events = [
    {
      event_id: 'EVT-0010-001',
      event_type: 'REPOSITIONING_ARRIVED',
      driver_id: 'DRV-042',
      zone_id: '882681a339fffff'
    }
  ];

  const toasts = extractArrivalToasts(events, seenEventIds);
  assert.equal(toasts.length, 0);
});

test('extractArrivalToasts consolidates multiple simultaneous arrivals into single toast', () => {
  const seenEventIds = new Set();
  const events = [
    {
      event_id: 'EVT-0020-001',
      event_type: 'REPOSITIONING_ARRIVED',
      driver_id: 'DRV-010',
      zone_id: '882681a339fffff'
    },
    {
      event_id: 'EVT-0020-002',
      event_type: 'REPOSITIONING_ARRIVED',
      driver_id: 'DRV-011',
      zone_id: '882681a339fffff'
    },
    {
      event_id: 'EVT-0020-003',
      event_type: 'REPOSITIONING_ARRIVED',
      driver_id: 'DRV-012',
      zone_id: '882681a30bfffff'
    }
  ];

  const toasts = extractArrivalToasts(events, seenEventIds);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].type, 'arrival');
  assert.equal(toasts[0].title, 'Simulated Riders Arrived');
  assert.ok(toasts[0].message.includes('3 simulated riders arrived'));
  assert.equal(seenEventIds.size, 3);
});

test('extractArrivalToasts ignores unrelated event types', () => {
  const seenEventIds = new Set();
  const events = [
    { event_id: 'EVT-0001', event_type: 'CUSTOMER_REQUEST_CREATED' },
    { event_id: 'EVT-0002', event_type: 'DISPATCH_ASSIGNED' },
    { event_id: 'EVT-0003', event_type: 'TRIP_STARTED' }
  ];

  const toasts = extractArrivalToasts(events, seenEventIds);
  assert.equal(toasts.length, 0);
});

test('detectPressureTransitions returns empty on initial baseline load', () => {
  const currentSupply = {
    '882681a339fffff': { pressure_status: 'CRITICAL', operational_pressure: 3.5 },
    '882681a30bfffff': { pressure_status: 'HIGH', operational_pressure: 1.8 }
  };

  // When prevSupply is null or undefined (first load / reset)
  const transitions = detectPressureTransitions(currentSupply, null);
  assert.equal(transitions.length, 0);
});

test('detectPressureTransitions detects genuine Critical to Moderate improvement', () => {
  const prevSupply = {
    '882681a339fffff': { pressure_status: 'CRITICAL', operational_pressure: 2.8 }
  };
  const currentSupply = {
    '882681a339fffff': { pressure_status: 'MODERATE', operational_pressure: 1.2 }
  };

  const transitions = detectPressureTransitions(currentSupply, prevSupply);
  assert.equal(transitions.length, 1);
  assert.equal(transitions[0].severity, 'success');
  assert.equal(transitions[0].type, 'pressure');
  assert.equal(transitions[0].title, 'Pressure Relieved');
  assert.ok(transitions[0].message.includes('Zone '));
  assert.ok(transitions[0].message.includes('CRITICAL'));
  assert.ok(transitions[0].message.includes('MODERATE'));
});

test('detectPressureTransitions detects worsening Moderate to High pressure', () => {
  const prevSupply = {
    '882681a339fffff': { pressure_status: 'MODERATE', operational_pressure: 1.1 }
  };
  const currentSupply = {
    '882681a339fffff': { pressure_status: 'HIGH', operational_pressure: 1.7 }
  };

  const transitions = detectPressureTransitions(currentSupply, prevSupply);
  assert.equal(transitions.length, 1);
  assert.equal(transitions[0].severity, 'warning');
  assert.equal(transitions[0].type, 'pressure');
  assert.equal(transitions[0].title, 'Pressure Elevated');
  assert.ok(transitions[0].message.includes('MODERATE'));
  assert.ok(transitions[0].message.includes('HIGH'));
});

test('detectPressureTransitions suppresses static / unchanging statuses', () => {
  const prevSupply = {
    '882681a339fffff': { pressure_status: 'CRITICAL', operational_pressure: 3.0 },
    '882681a30bfffff': { pressure_status: 'LOW', operational_pressure: 0.4 }
  };
  const currentSupply = {
    '882681a339fffff': { pressure_status: 'CRITICAL', operational_pressure: 2.9 },
    '882681a30bfffff': { pressure_status: 'LOW', operational_pressure: 0.4 }
  };

  const transitions = detectPressureTransitions(currentSupply, prevSupply);
  assert.equal(transitions.length, 0);
});

test('detectPressureTransitions consolidates bursts of 4 or more zone transitions', () => {
  const prevSupply = {};
  const currentSupply = {};

  for (let i = 0; i < 5; i++) {
    const zoneId = `mock_zone_${i}`;
    prevSupply[zoneId] = { pressure_status: 'CRITICAL', operational_pressure: 3.0 };
    currentSupply[zoneId] = { pressure_status: 'MODERATE', operational_pressure: 1.0 };
  }

  const transitions = detectPressureTransitions(currentSupply, prevSupply);
  assert.equal(transitions.length, 1);
  assert.equal(transitions[0].title, 'Zone Pressure Improved');
  assert.ok(transitions[0].message.includes('5 zones improved'));
  assert.equal(transitions[0].severity, 'success');
});
