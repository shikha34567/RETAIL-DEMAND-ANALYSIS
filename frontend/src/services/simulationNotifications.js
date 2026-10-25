/**
 * RideIntel Simulation Notification Engine.
 *
 * Deterministic helpers for:
 * 1. Dispatch response summaries and deduplication.
 * 2. Kinematic arrival event formatting and grouping.
 * 3. Canonical zone operational pressure transitions and burst grouping.
 * 4. Toast queue limits (max 4 visible, auto-dismiss).
 */

import { getZoneLabel } from './zoneLabels.js';

export const PRESSURE_SEVERITY_RANK = {
  LOW: 0,
  MODERATE: 1,
  HIGH: 2,
  CRITICAL: 3,
  NO_CAPACITY: 3
};

/**
 * Categorizes whether a pressure level transition is an improvement or worsening.
 */
export function evaluatePressureTransition(oldLevel, newLevel) {
  if (!oldLevel || !newLevel || oldLevel === newLevel) return null;

  const oldRank = PRESSURE_SEVERITY_RANK[oldLevel] ?? 1;
  const newRank = PRESSURE_SEVERITY_RANK[newLevel] ?? 1;

  if (newRank < oldRank) {
    return { direction: 'IMPROVED', severity: 'success' };
  } else if (newRank > oldRank) {
    return { direction: 'WORSENED', severity: 'warning' };
  }
  return { direction: 'CHANGED', severity: 'info' };
}

/**
 * Creates a structured dispatch toast notification from an authoritative dispatch response.
 */
export function createDispatchToast(dispatchResult) {
  if (!dispatchResult || typeof dispatchResult !== 'object' || Object.keys(dispatchResult).length === 0) return null;

  const assignedCount = dispatchResult.drivers_assigned ?? dispatchResult.dispatched_count ?? 0;
  const assignments = dispatchResult.assignments || [];

  if (assignedCount > 0) {
    // Unique destination zones
    const destZones = Array.from(new Set(assignments.map(a => a.destination_zone || a.target_zone_id).filter(Boolean)));
    const destLabels = destZones.slice(0, 2).map(z => getZoneLabel(z));
    const extraCount = destZones.length - destLabels.length;
    const destSummary = extraCount > 0
      ? `${destLabels.join(', ')} +${extraCount} more`
      : destLabels.join(', ');

    return {
      id: `dispatch-${Date.now()}-${assignedCount}`,
      type: 'dispatch',
      severity: 'info',
      title: 'Status Update Completed',
      message: `${assignedCount} simulated rider${assignedCount > 1 ? 's' : ''} dispatched toward ${destSummary}.`,
      detail: dispatchResult.explanation || `Repositioning initiated across H3 rings.`,
      timestamp: new Date().toISOString(),
      createdAt: Date.now()
    };
  }

  // 0 vehicles dispatched: report real reason
  const reasons = dispatchResult.skipped_reasons || {};
  let reasonText = 'Origin coverage floors maintained';
  if (reasons.NO_SURPLUS_DONOR_WITHIN_RADIUS) {
    reasonText = 'No surplus idle donors within search radius';
  } else if (reasons.DESTINATION_CAP_REACHED) {
    reasonText = 'Destination vehicle cap reached';
  } else if (dispatchResult.explanation) {
    reasonText = dispatchResult.explanation;
  }

  return {
    id: `dispatch-${Date.now()}-zero`,
    type: 'dispatch',
    severity: 'neutral',
    title: 'Status Update: 0 Dispatched',
    message: `0 simulated riders assigned — ${reasonText}.`,
    detail: 'All idle vehicles retained to protect origin zone coverage floors.',
    timestamp: new Date().toISOString(),
    createdAt: Date.now()
  };
}

/**
 * Detects genuine zone pressure level changes by comparing current state against previous confirmed state.
 * Returns an array of toast objects (or grouped summary toast if burst >= 4).
 */
export function detectPressureTransitions(currentZoneSupply, previousZoneSupply) {
  if (!currentZoneSupply || !previousZoneSupply) return [];

  const transitions = [];

  for (const [cell, currentData] of Object.entries(currentZoneSupply)) {
    const prevData = previousZoneSupply[cell];
    if (!prevData) continue;

    const prevLevel = prevData.pressure_level || prevData.pressure_status;
    const currLevel = currentData.pressure_level || currentData.pressure_status;

    if (prevLevel && currLevel && prevLevel !== currLevel) {
      const evaluation = evaluatePressureTransition(prevLevel, currLevel);
      if (evaluation) {
        transitions.push({
          cell,
          label: getZoneLabel(cell),
          prevLevel,
          currLevel,
          direction: evaluation.direction,
          severity: evaluation.severity
        });
      }
    }
  }

  if (transitions.length === 0) return [];

  // If burst of >= 4 zones changed in the same tick, group them into a summary toast
  if (transitions.length >= 4) {
    const improved = transitions.filter(t => t.direction === 'IMPROVED');
    const worsened = transitions.filter(t => t.direction === 'WORSENED');

    const toasts = [];
    if (improved.length > 0) {
      toasts.push({
        id: `pressure-burst-imp-${Date.now()}`,
        type: 'pressure',
        severity: 'success',
        title: 'Zone Pressure Improved',
        message: `${improved.length} zones improved (${improved.slice(0, 2).map(t => t.label).join(', ')}${improved.length > 2 ? ` +${improved.length - 2} more` : ''}).`,
        detail: 'Simulated vehicle arrivals satisfied local forecast ride demand.',
        timestamp: new Date().toISOString(),
        createdAt: Date.now()
      });
    }
    if (worsened.length > 0) {
      toasts.push({
        id: `pressure-burst-worse-${Date.now()}`,
        type: 'pressure',
        severity: 'warning',
        title: 'Zone Pressure Elevated',
        message: `${worsened.length} zones worsened (${worsened.slice(0, 2).map(t => t.label).join(', ')}${worsened.length > 2 ? ` +${worsened.length - 2} more` : ''}).`,
        detail: 'Local demand outpaced available physically idle capacity.',
        timestamp: new Date().toISOString(),
        createdAt: Date.now()
      });
    }
    return toasts;
  }

  // Otherwise, produce individual toasts (up to 3)
  return transitions.slice(0, 3).map((t, idx) => ({
    id: `pressure-${t.cell}-${Date.now()}-${idx}`,
    type: 'pressure',
    severity: t.severity,
    title: t.direction === 'IMPROVED' ? 'Pressure Relieved' : 'Pressure Elevated',
    message: `${t.label}: ${t.prevLevel} \u2192 ${t.currLevel}`,
    zoneId: t.cell,
    detail: t.direction === 'IMPROVED'
      ? 'Arrived simulated capacity satisfied forecast ride demand.'
      : 'Forecast demand outpaced available physically idle supply.',
    timestamp: new Date().toISOString(),
    createdAt: Date.now()
  }));
}

/**
 * Extracts and formats arrival events from backend recent_events that haven't been seen yet.
 */
export function extractArrivalToasts(recentEvents, seenEventIds) {
  if (!recentEvents || recentEvents.length === 0) return [];

  const newArrivalEvents = recentEvents.filter(e => {
    if (seenEventIds.has(e.event_id)) return false;
    seenEventIds.add(e.event_id);
    return e.event_type === 'REPOSITIONING_ARRIVED';
  });

  if (newArrivalEvents.length === 0) return [];

  // If multiple arrivals in one tick, group them
  if (newArrivalEvents.length > 2) {
    const uniqueZones = Array.from(new Set(newArrivalEvents.map(e => e.zone_id).filter(Boolean)));
    return [{
      id: `arrival-grouped-${Date.now()}`,
      type: 'arrival',
      severity: 'info',
      title: 'Simulated Riders Arrived',
      message: `${newArrivalEvents.length} simulated riders arrived across ${uniqueZones.length} demand zone${uniqueZones.length > 1 ? 's' : ''}.`,
      detail: 'Vehicles restored to IDLE status and added to destination capacity.',
      timestamp: new Date().toISOString(),
      createdAt: Date.now()
    }];
  }

  return newArrivalEvents.map((evt, idx) => {
    const zoneName = evt.zone_id ? getZoneLabel(evt.zone_id) : 'target zone';
    return {
      id: evt.event_id || `arrival-${Date.now()}-${idx}`,
      type: 'arrival',
      severity: 'info',
      title: 'Simulated Rider Arrived',
      message: `Rider ${evt.driver_id || 'fleet'} reached demand hotspot ${zoneName}.`,
      driverId: evt.driver_id,
      zoneId: evt.zone_id,
      detail: 'Restored to IDLE at destination; capacity recalculated.',
      timestamp: evt.sim_time || new Date().toISOString(),
      createdAt: Date.now()
    };
  });
}
