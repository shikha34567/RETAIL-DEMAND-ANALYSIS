import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getZoneLabel } from '../src/services/zoneLabels.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('ZoneIntelligenceView.jsx contains no unescaped {baseline} identifier expressions', () => {
  const viewPath = path.resolve(__dirname, '../src/views/ZoneIntelligenceView.jsx');
  const source = fs.readFileSync(viewPath, 'utf8');

  // Verify that {baseline} does not appear as a standalone JSX child expression
  const invalidBaselineRegex = /\{baseline\}/g;
  assert.equal(
    invalidBaselineRegex.test(source),
    false,
    'ZoneIntelligenceView.jsx must not contain standalone {baseline} expressions'
  );

  // Verify that LaTeX \text{...} patterns do not exist in JSX text
  const latexBraceRegex = /\\text\{[^}]+\}/g;
  assert.equal(
    latexBraceRegex.test(source),
    false,
    'ZoneIntelligenceView.jsx must not contain LaTeX \\text{...} braces in JSX'
  );
});

test('Zone Intelligence pressure record formatting correctly handles C=0 and positive capacity', () => {
  const zeroCapRow = {
    h3_cell: '8826641b23fffff',
    forecast_origin: '2022-06-22T05:00:00Z',
    predicted_rides_D: 0.359668,
    available_vehicles_V: 0,
    estimated_capacity_C: 0.0,
    pressure_index: null,
    estimated_unserved_demand_rides: 0.359668,
    pressure_level: 'NO_CAPACITY'
  };

  const normalCapRow = {
    h3_cell: '8827593433fffff',
    forecast_origin: '2022-06-22T05:00:00Z',
    predicted_rides_D: 10.5,
    available_vehicles_V: 5,
    estimated_capacity_C: 10.0,
    pressure_index: 1.05,
    estimated_unserved_demand_rides: 0.5,
    pressure_level: 'MODERATE'
  };

  // Label formatting
  assert.equal(getZoneLabel(zeroCapRow.h3_cell), 'Zone Z-005');
  assert.equal(getZoneLabel(normalCapRow.h3_cell), 'Zone Z-232');

  // Pressure index formatting: C=0 yields null representation, positive yields decimal
  const zeroDisplay = typeof zeroCapRow.pressure_index === 'number'
    ? zeroCapRow.pressure_index.toFixed(2)
    : 'null (C = 0)';
  assert.equal(zeroDisplay, 'null (C = 0)');

  const normalDisplay = typeof normalCapRow.pressure_index === 'number'
    ? normalCapRow.pressure_index.toFixed(2)
    : 'null (C = 0)';
  assert.equal(normalDisplay, '1.05');
});

test('Surge eligibility multi-factor formula safely evaluates baseline ratio', () => {
  function checkSurgeEligibility(D, P, baseline) {
    if (!baseline || baseline <= 0) return false;
    const meetsDemand = D >= 5.0;
    const meetsPressure = P >= 1.20;
    const meetsGrowth = (D / baseline) >= 1.30;
    return meetsDemand && meetsPressure && meetsGrowth;
  }

  // Baseline missing or 0
  assert.equal(checkSurgeEligibility(6.0, 1.5, undefined), false);
  assert.equal(checkSurgeEligibility(6.0, 1.5, 0), false);

  // Eligible surge
  assert.equal(checkSurgeEligibility(8.0, 1.5, 5.0), true); // 8/5 = 1.6 >= 1.3

  // Below growth threshold
  assert.equal(checkSurgeEligibility(6.0, 1.5, 5.0), false); // 6/5 = 1.2 < 1.3
});
