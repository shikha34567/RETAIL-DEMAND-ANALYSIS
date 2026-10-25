import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const geojsonPath = path.resolve(__dirname, '../src/services/chicagoH3Zones.json');
const rawGeoJSON = fs.readFileSync(geojsonPath, 'utf8');
const geojson = JSON.parse(rawGeoJSON);

test('chicagoH3Zones.json contains exactly 239 Resolution 8 features', () => {
  assert.equal(geojson.type, 'FeatureCollection');
  assert.equal(Array.isArray(geojson.features), true);
  assert.equal(geojson.features.length, 239);
});

test('every feature in chicagoH3Zones has valid geometry and closed polygon ring', () => {
  geojson.features.forEach((feature, idx) => {
    assert.equal(feature.type, 'Feature');
    assert.ok(feature.id, `Feature #${idx} missing id`);
    assert.equal(feature.geometry.type, 'Polygon');
    assert.equal(feature.geometry.coordinates.length, 1);

    const ring = feature.geometry.coordinates[0];
    assert.equal(ring.length, 7, `Feature ${feature.id} does not have 7 coordinates in closed hexagon ring`);

    // Verify first and last points are identical (closed polygon)
    const first = ring[0];
    const last = ring[ring.length - 1];
    assert.equal(first[0], last[0], `Feature ${feature.id} polygon ring is not closed (lng mismatch)`);
    assert.equal(first[1], last[1], `Feature ${feature.id} polygon ring is not closed (lat mismatch)`);

    // Verify coordinates fall within Chicago metropolitan bounding box
    ring.forEach(([lng, lat]) => {
      assert.ok(lat >= 41.60 && lat <= 42.10, `Latitude ${lat} out of Chicago bounds for ${feature.id}`);
      assert.ok(lng >= -87.95 && lng <= -87.50, `Longitude ${lng} out of Chicago bounds for ${feature.id}`);
    });
  });
});

test('every feature in chicagoH3Zones has canonical properties matching zone catalog', () => {
  geojson.features.forEach((feature) => {
    const props = feature.properties;
    assert.ok(props.h3_index.startsWith('882664') || props.h3_index.startsWith('882759'));
    assert.match(props.label, /^Zone Z-\d{3}$/);
    assert.equal(props.resolution, 8);
    assert.ok(props.lat >= 41.60 && props.lat <= 42.10);
    assert.ok(props.lng >= -87.95 && props.lng <= -87.50);
  });
});

test('heatmap tier thresholds map demand accurately', () => {
  const HEATMAP_TIERS = [
    { max: 0.1, color: '#334155' },
    { max: 1.0, color: '#0284c7' },
    { max: 5.0, color: '#06b6d4' },
    { max: 15.0, color: '#10b981' },
    { max: 35.0, color: '#f59e0b' },
    { max: Infinity, color: '#f43f5e' }
  ];

  function getDemandColor(demand) {
    if (demand == null || demand <= 0) return '#1e293b';
    for (const tier of HEATMAP_TIERS) {
      if (demand <= tier.max) return tier.color;
    }
    return '#f43f5e';
  }

  assert.equal(getDemandColor(0), '#1e293b');
  assert.equal(getDemandColor(null), '#1e293b');
  assert.equal(getDemandColor(0.05), '#334155');
  assert.equal(getDemandColor(0.36), '#0284c7'); // Zone Z-005 prediction
  assert.equal(getDemandColor(2.5), '#06b6d4');
  assert.equal(getDemandColor(12.0), '#10b981');
  assert.equal(getDemandColor(28.0), '#f59e0b');
  assert.equal(getDemandColor(50.0), '#f43f5e'); // Downtown peak demand
});

