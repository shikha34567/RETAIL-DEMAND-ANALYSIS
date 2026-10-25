import test from 'node:test';
import assert from 'node:assert/strict';
import { getZoneLabel, getZoneDetails, getAllZoneLabels } from '../src/services/zoneLabels.js';

test('getZoneLabel returns deterministic friendly label for known cell', () => {
  // Cell index 42 is 882664c145fffff -> Zone Z-042
  assert.equal(getZoneLabel('882664c145fffff'), 'Zone Z-042');
  // First cell is 8826641915fffff -> Zone Z-001
  assert.equal(getZoneLabel('8826641915fffff'), 'Zone Z-001');
});

test('getZoneLabel handles null, undefined and unknown gracefully', () => {
  assert.equal(getZoneLabel(null), 'Unknown Zone');
  assert.equal(getZoneLabel(undefined), 'Unknown Zone');
  assert.equal(getZoneLabel('unknown_hex_1234'), 'Zone 1234');
});

test('getZoneDetails returns valid coordinates and resolution', () => {
  const details = getZoneDetails('882664c145fffff');
  assert.equal(details.label, 'Zone Z-042');
  assert.equal(details.resolution, 8);
  assert.ok(typeof details.lat === 'number');
  assert.ok(typeof details.lng === 'number');
  assert.ok(details.coordinates.includes('41.'));
  assert.ok(details.coordinates.includes('-87.'));
});

test('getAllZoneLabels returns all 239 catalog entries sorted', () => {
  const all = getAllZoneLabels();
  assert.equal(all.length, 239);
  assert.equal(all[0].label, 'Zone Z-001');
  assert.equal(all[238].label, 'Zone Z-239');
});

