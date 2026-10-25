import test from 'node:test';
import assert from 'node:assert/strict';

function formatChicagoTime(utcString, includeSeconds = false) {
  if (!utcString) return '—';
  try {
    const d = new Date(utcString);
    if (isNaN(d.getTime())) return utcString;

    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Chicago',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: includeSeconds ? '2-digit' : undefined,
      hour12: true,
      timeZoneName: 'short'
    }).format(d);
  } catch {
    return utcString;
  }
}

function formatChicagoTimeOnly(utcString) {
  if (!utcString) return '—';
  try {
    const d = new Date(utcString);
    if (isNaN(d.getTime())) return utcString;

    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Chicago',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short'
    }).format(d);
  } catch {
    return utcString;
  }
}

class ApiError extends Error {
  constructor(message, status = 500, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

test('formatChicagoTime converts UTC to Chicago Daylight Time (CDT)', () => {
  // June 22, 2022 05:00:00 UTC is midnight (12:00 AM) CDT
  const formattedMidnight = formatChicagoTime('2022-06-22T05:00:00Z');
  assert.ok(formattedMidnight.includes('Jun 22, 2022'));
  assert.ok(formattedMidnight.includes('12:00 AM'));
  assert.ok(formattedMidnight.includes('CDT'));

  // June 22, 2022 17:15:00 UTC is 12:15 PM CDT
  const formattedNoon = formatChicagoTime('2022-06-22T17:15:00Z');
  assert.ok(formattedNoon.includes('Jun 22, 2022'));
  assert.ok(formattedNoon.includes('12:15 PM'));
  assert.ok(formattedNoon.includes('CDT'));

  // Test with seconds
  const formattedSec = formatChicagoTime('2022-06-22T17:15:30Z', true);
  assert.ok(formattedSec.includes('12:15:30 PM'));

  // ISO string with +00:00 offset
  const formattedOffset = formatChicagoTime('2022-06-22T05:00:00+00:00');
  assert.ok(formattedOffset.includes('12:00 AM'));
});

test('formatChicagoTimeOnly formats time portion in America/Chicago', () => {
  const timeOnly = formatChicagoTimeOnly('2022-06-22T05:00:00Z');
  assert.ok(timeOnly.includes('12:00 AM'));
  assert.ok(timeOnly.includes('CDT'));

  const timeNoon = formatChicagoTimeOnly('2022-06-22T17:15:00Z');
  assert.ok(timeNoon.includes('12:15 PM'));
  assert.ok(timeNoon.includes('CDT'));
});

test('formatChicagoTime handles empty, null and invalid inputs gracefully', () => {
  assert.equal(formatChicagoTime(null), '—');
  assert.equal(formatChicagoTime(undefined), '—');
  assert.equal(formatChicagoTime(''), '—');
  assert.equal(formatChicagoTime('not-a-timestamp'), 'not-a-timestamp');

  assert.equal(formatChicagoTimeOnly(null), '—');
  assert.equal(formatChicagoTimeOnly(undefined), '—');
  assert.equal(formatChicagoTimeOnly(''), '—');
  assert.equal(formatChicagoTimeOnly('invalid'), 'invalid');
});

test('ApiError preserves HTTP status and payload detail', () => {
  const err = new ApiError('Not Found', 404, { detail: 'Zone not found' });
  assert.equal(err.name, 'ApiError');
  assert.equal(err.message, 'Not Found');
  assert.equal(err.status, 404);
  assert.deepEqual(err.detail, { detail: 'Zone not found' });
});
