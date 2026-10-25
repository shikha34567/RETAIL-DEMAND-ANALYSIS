/**
 * RideIntel Centralized API Service.
 *
 * Connects to the FastAPI backend (/api/v1) and handles:
 * - Query parameter serialization
 * - Unified error extraction
 * - UTC to America/Chicago timestamp formatting
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

/**
 * Custom API error containing status code and backend detail.
 */
export class ApiError extends Error {
  constructor(message, status = 500, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Formats a UTC ISO-8601 string to America/Chicago local time.
 * E.g., '2022-06-22T05:00:00Z' -> 'Jun 22, 2022, 12:00 AM CDT'
 */
export function formatChicagoTime(utcString, includeSeconds = false) {
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

/**
 * Formats a UTC ISO-8601 string to America/Chicago time only (e.g. '12:00 AM CDT').
 */
export function formatChicagoTimeOnly(utcString) {
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

/**
 * Generic fetch wrapper with standardized error handling.
 */
async function apiRequest(endpoint, params = {}) {
  const url = new URL(`${window.location.origin}${API_BASE_URL}${endpoint}`);

  Object.entries(params).forEach(([key, val]) => {
    if (val !== null && val !== undefined && val !== '') {
      url.searchParams.append(key, val);
    }
  });

  try {
    const response = await fetch(url.toString(), {
      headers: {
        'Accept': 'application/json',
      },
    });

    const isJson = response.headers.get('content-type')?.includes('application/json');
    const data = isJson ? await response.json() : null;

    if (!response.ok) {
      const errorMsg = data?.detail || `HTTP ${response.status}: ${response.statusText}`;
      throw new ApiError(errorMsg, response.status, data);
    }

    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      err.message === 'Failed to fetch'
        ? 'Could not connect to FastAPI backend at http://127.0.0.1:8000. Ensure the server is running.'
        : err.message,
      0
    );
  }
}

// -----------------------------------------------------------------------------
// Endpoint Callers
// -----------------------------------------------------------------------------

export async function fetchHealth() {
  return apiRequest('/health');
}

export async function fetchMetadata() {
  return apiRequest('/metadata');
}

export async function fetchForecasts({ model = 'xgboost', zone, start, end, limit = 50, offset = 0 } = {}) {
  return apiRequest('/forecasts', { model, zone, start, end, limit, offset });
}

export async function fetchPressure({ zone, pressure_level, start, end, limit = 50, offset = 0 } = {}) {
  return apiRequest('/pressure', { zone, pressure_level, start, end, limit, offset });
}

export async function fetchSurgeAlerts({ zone, severity, start, end, limit = 50, offset = 0 } = {}) {
  return apiRequest('/surge-alerts', { zone, severity, start, end, limit, offset });
}

export async function fetchMetrics(model = null) {
  return apiRequest('/metrics', { model });
}

/**
 * Generic POST wrapper.
 */
async function apiPost(endpoint, body = {}, params = {}) {
  const url = new URL(`${window.location.origin}${API_BASE_URL}${endpoint}`);

  Object.entries(params).forEach(([key, val]) => {
    if (val !== null && val !== undefined && val !== '') {
      url.searchParams.append(key, val);
    }
  });

  try {
    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const isJson = response.headers.get('content-type')?.includes('application/json');
    const data = isJson ? await response.json() : null;

    if (!response.ok) {
      const errorMsg = data?.detail || `HTTP ${response.status}: ${response.statusText}`;
      throw new ApiError(errorMsg, response.status, data);
    }

    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      err.message === 'Failed to fetch'
        ? 'Could not connect to FastAPI backend at http://127.0.0.1:8000.'
        : err.message,
      0
    );
  }
}

// -----------------------------------------------------------------------------
// Fleet Simulation Endpoints
// -----------------------------------------------------------------------------

export async function fetchSimulationState(origin = null) {
  return apiRequest('/simulation/state', { origin });
}

export async function resetSimulation(origin = null) {
  return apiPost('/simulation/reset', {}, { origin });
}

export async function dispatchFleet(origin = null) {
  return apiPost('/simulation/dispatch', {}, { origin });
}

export async function stepSimulation(seconds = 30) {
  return apiPost('/simulation/step', { seconds });
}

export async function createCustomerRequest(payload) {
  return apiPost('/simulation/customer-requests', payload);
}

export async function cancelCustomerRequest(requestId) {
  return apiPost(`/simulation/customer-requests/${requestId}/cancel`);
}

export async function fetchTrips() {
  return apiRequest('/simulation/trips');
}

export async function fetchSimulationEvents(limit = 50) {
  return apiRequest('/simulation/events', { limit });
}



