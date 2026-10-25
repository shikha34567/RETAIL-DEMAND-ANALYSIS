import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import chicagoH3Zones from '../services/chicagoH3Zones.json';
import chicagoSquareGrid from '../services/chicagoSquareGrid.json';
import {
  fetchPressure,
  formatChicagoTime,
  fetchSimulationState,
  resetSimulation,
  dispatchFleet,
  stepSimulation,
  createCustomerRequest,
  cancelCustomerRequest,
  fetchSimulationEvents
} from '../services/api';
import { getZoneLabel, getZoneDetails, getAllZoneLabels } from '../services/zoneLabels';
import Badge from '../components/Badge';
import { LoadingState, ErrorState } from '../components/States';
import SimulationToastContainer from '../components/SimulationToastContainer';
import {
  createDispatchToast,
  detectPressureTransitions,
  extractArrivalToasts
} from '../services/simulationNotifications';
import {
  Layers,
  RefreshCw,
  Compass,
  Play,
  Pause,
  FastForward,
  RotateCcw,
  Navigation,
  Car,
  X,
  PhoneCall,
  CheckCircle2,
  MapPin,
  Grid,
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Maximize2,
  Minimize2,
  SlidersHorizontal,
  Flame,
  ShieldAlert
} from 'lucide-react';

// Representative snapshot origins across the held-out test split
const SAMPLE_ORIGINS = [
  { id: '2022-06-22T05:00:00Z', label: 'Jun 22, 12:00 AM CDT — Night Baseline' },
  { id: '2022-06-22T13:00:00Z', label: 'Jun 22, 08:00 AM CDT — Commute Peak' },
  { id: '2022-06-22T15:00:00Z', label: 'Jun 22, 10:00 AM CDT — Midday Shortage' },
  { id: '2022-06-22T22:00:00Z', label: 'Jun 22, 05:00 PM CDT — Evening Rush' },
  { id: '2022-06-23T17:00:00Z', label: 'Jun 23, 12:00 PM CDT — Midday Shortage' },
  { id: '2022-06-25T04:00:00Z', label: 'Jun 24, 11:00 PM CDT — Night Entertainment' },
  { id: '2022-06-30T15:00:00Z', label: 'Jun 30, 10:00 AM CDT — High Shortage' },
];

// Authoritative vehicle state colors conforming to specification:
// IDLE: green, REPOSITIONING: blue, TO_PICKUP: amber, WITH_PASSENGER: red, OFF_DUTY: slate
const DRIVER_STATUS_COLORS = {
  IDLE: '#10b981',          // Green
  REPOSITIONING: '#3b82f6', // Blue
  TO_PICKUP: '#f59e0b',     // Amber
  WITH_PASSENGER: '#ef4444',// Red
  OFF_DUTY: '#64748b'       // Slate
};

// Continuous color gradient stops for heatmap visual scale:
// 0.00 -> Teal (#0f766e: [15, 118, 110])
// 0.25 -> Green (#10b981: [16, 185, 129])
// 0.50 -> Yellow (#eab308: [234, 179, 8])
// 0.75 -> Orange (#f97316: [249, 115, 22])
// 1.00 -> Red (#ef4444: [239, 68, 68])
function interpolateRgb(c1, c2, factor) {
  const f = Math.max(0, Math.min(1, factor));
  const r = Math.round(c1[0] + f * (c2[0] - c1[0]));
  const g = Math.round(c1[1] + f * (c2[1] - c1[1]));
  const b = Math.round(c1[2] + f * (c2[2] - c1[2]));
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Returns a continuous interpolated color on the Teal -> Green -> Yellow -> Orange -> Red scale.
 * Note: Used solely for visual heatmap styling; never alters underlying operational metrics.
 */
function getHeatmapVisualColor(score) {
  const s = Math.max(0, Math.min(1, score));
  if (s <= 0.25) {
    return interpolateRgb([15, 118, 110], [16, 185, 129], s / 0.25);
  } else if (s <= 0.50) {
    return interpolateRgb([16, 185, 129], [234, 179, 8], (s - 0.25) / 0.25);
  } else if (s <= 0.75) {
    return interpolateRgb([234, 179, 8], [249, 115, 22], (s - 0.50) / 0.25);
  } else {
    return interpolateRgb([249, 115, 22], [239, 68, 68], (s - 0.75) / 0.25);
  }
}

// Calculate travel bearing between two coordinates in degrees [0, 360)
function calculateBearing(lat1, lon1, lat2, lon2) {
  if (lat1 === lat2 && lon1 === lon2) return 0;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const deltaLambda = ((lon2 - lon1) * Math.PI) / 180;
  const y = Math.sin(deltaLambda) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.cos(phi2) * Math.cos(deltaLambda);
  const theta = Math.atan2(y, x);
  return Math.round(((theta * 180) / Math.PI + 360) % 360);
}

// Leaflet DivIcon creating a recognizable motorcycle/scooter icon rotated by travel heading
function createMotorcycleIcon(driver, isSelected) {
  const color = DRIVER_STATUS_COLORS[driver.status] || '#10b981';
  let rotation = 0;
  if (driver.target_lat && driver.target_lng) {
    const oLat = driver.origin_lat || driver.lat;
    const oLng = driver.origin_lng || driver.lng;
    rotation = calculateBearing(oLat, oLng, driver.target_lat, driver.target_lng);
  }

  const borderStyle = isSelected
    ? '2px solid #38bdf8'
    : `2px solid ${color}`;
  const shadowStyle = isSelected
    ? '0 0 12px #38bdf8, 0 2px 8px rgba(0,0,0,0.9)'
    : `0 2px 6px rgba(0,0,0,0.8), 0 0 6px ${color}55`;

  const html = `
    <div style="
      transform: rotate(${rotation}deg);
      transition: transform 0.3s ease-out;
      width: 28px;
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #020617;
      border: ${borderStyle};
      border-radius: 9999px;
      box-shadow: ${shadowStyle};
      cursor: pointer;
    ">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="18.5" cy="17.5" r="3.5"/>
        <circle cx="5.5" cy="17.5" r="3.5"/>
        <circle cx="15" cy="5" r="1"/>
        <path d="M12 17.5V14l-3-3 4-3 2 3h2"/>
      </svg>
    </div>
  `;

  return L.divIcon({
    html,
    className: 'motorcycle-marker-container',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16]
  });
}

/**
 * Aggregates cell data for a square grid feature:
 * - Computes authoritative operational demand D, idle fleet V, capacity C, shortage, pressure_level.
 * - Computes a separate normalized continuous visual score for heatmap coloring.
 * IMPORTANT: Visual score is strictly decoupled from operational formulas.
 */
function aggregateSquareTelemetry(squareFeature, zoneRecords, simState) {
  const h3Cells = squareFeature.properties.h3_cells || [];
  let totalDemand = 0;
  let trackedCount = 0;

  // Actual idle vehicles currently located in this square
  const driversInSquare = (simState?.drivers || []).filter(d => h3Cells.includes(d.current_h3_cell));
  const totalIdleVehicles = driversInSquare.filter(d => d.status === 'IDLE').length;

  // Active trips activity in this square (context only)
  const totalIncoming = (simState?.drivers || []).filter(
    d => d.status === 'REPOSITIONING' && h3Cells.includes(d.destination_h3_cell)
  ).length;
  const totalPickups = (simState?.active_trips || []).filter(
    t => h3Cells.includes(t.pickup_h3_cell) && (t.status === 'REQUESTED' || t.status === 'ASSIGNED')
  ).length;
  const totalDropoffs = (simState?.active_trips || []).filter(
    t => h3Cells.includes(t.dropoff_h3_cell) && (t.status === 'ON_TRIP' || t.status === 'ASSIGNED')
  ).length;

  h3Cells.forEach(cell => {
    const simCell = simState?.zone_supply?.[cell];
    const rec = zoneRecords[cell];
    if (simCell && simCell.predicted_demand_D !== undefined && simCell.predicted_demand_D !== null) {
      trackedCount++;
      totalDemand += simCell.predicted_demand_D;
    } else if (rec) {
      trackedCount++;
      totalDemand += (rec.predicted_rides_D || 0);
    }
  });

  // Authoritative operational calculations: C = V * 2.0
  const capacity = Math.round(totalIdleVehicles * 2.0 * 10) / 10;
  const shortage = Math.max(0, Math.round((totalDemand - capacity) * 100) / 100);

  // Authoritative operational pressure level (contracts/parquet_schemas.md Table 6)
  let pressureLevel = 'LOW';
  let pressureStatus = 'NORMAL';

  if (trackedCount === 0 && totalDemand === 0 && totalIdleVehicles === 0) {
    pressureLevel = 'NO_DATA';
    pressureStatus = 'NO_FORECAST_DATA';
  } else if (capacity === 0 && totalDemand > 0) {
    pressureLevel = 'NO_CAPACITY';
    pressureStatus = 'NO_ESTIMATED_CAPACITY';
  } else if (capacity === 0 && totalDemand === 0) {
    pressureLevel = 'LOW';
    pressureStatus = 'NORMAL';
  } else {
    const ratio = totalDemand / capacity;
    if (ratio < 0.8) {
      pressureLevel = 'LOW';
      pressureStatus = 'NORMAL';
    } else if (ratio <= 1.0) {
      pressureLevel = 'MODERATE';
      pressureStatus = 'ELEVATED';
    } else if (ratio < 1.2) {
      pressureLevel = 'HIGH';
      pressureStatus = 'HIGH_PRESSURE';
    } else {
      pressureLevel = 'CRITICAL';
      pressureStatus = 'HIGH_PRESSURE';
    }
  }

  // Visual Intensity Score (0.0 to 1.0) strictly bounded by operational pressure tier.
  // Rule: Never let visual smoothing override operational pressure classification.
  // Score mapping:
  //   NO_DATA: 0.00
  //   LOW: 0.06 - 0.25 (Teal -> Emerald Green)
  //   MODERATE: 0.26 - 0.50 (Lime Green -> Yellow)
  //   HIGH: 0.51 - 0.75 (Yellow -> Orange)
  //   CRITICAL / NO_CAPACITY: 0.76 - 1.00 (Orange -> Red)
  let visualScore = 0.0;
  let fillColor = '#1e293b';
  let fillOpacity = 0.15;

  if (pressureLevel === 'NO_DATA') {
    visualScore = 0.0;
    fillColor = '#1e293b';
    fillOpacity = 0.12;
  } else if (pressureLevel === 'LOW') {
    const ratio = capacity > 0 ? (totalDemand / capacity) : 0.0;
    const rel = Math.max(0.0, Math.min(1.0, ratio / 0.8));
    visualScore = 0.06 + rel * (0.25 - 0.06);
    fillColor = getHeatmapVisualColor(visualScore);
    fillOpacity = 0.50;
  } else if (pressureLevel === 'MODERATE') {
    const ratio = capacity > 0 ? (totalDemand / capacity) : 0.9;
    const rel = Math.max(0.0, Math.min(1.0, (ratio - 0.8) / 0.2));
    visualScore = 0.26 + rel * (0.50 - 0.26);
    fillColor = getHeatmapVisualColor(visualScore);
    fillOpacity = 0.55;
  } else if (pressureLevel === 'HIGH') {
    const ratio = capacity > 0 ? (totalDemand / capacity) : 1.1;
    const rel = Math.max(0.0, Math.min(1.0, (ratio - 1.0) / 0.2));
    visualScore = 0.51 + rel * (0.75 - 0.51);
    fillColor = getHeatmapVisualColor(visualScore);
    fillOpacity = 0.60;
  } else {
    // CRITICAL or NO_CAPACITY
    if (totalDemand <= 0.15 && totalIdleVehicles === 0) {
      // Trace demand with no vehicles: minimal visual activity (teal stop)
      visualScore = 0.08;
      fillColor = getHeatmapVisualColor(visualScore);
      fillOpacity = 0.45;
    } else {
      if (capacity > 0) {
        const ratio = totalDemand / capacity;
        const rel = Math.max(0.0, Math.min(1.0, (ratio - 1.2) / 1.5));
        visualScore = 0.76 + rel * (1.00 - 0.76);
      } else {
        const rel = Math.max(0.0, Math.min(1.0, totalDemand / 12.0));
        visualScore = 0.80 + rel * 0.20;
      }
      fillColor = getHeatmapVisualColor(visualScore);
      fillOpacity = 0.65;
    }
  }

  const projectedCapacity = Math.round((totalIdleVehicles + totalIncoming) * 2.0 * 10) / 10;

  return {
    grid_id: squareFeature.id || squareFeature.properties.grid_id,
    label: squareFeature.properties.label || `Square ${squareFeature.id}`,
    h3_cells: h3Cells,
    h3_count: h3Cells.length,
    tracked_h3_count: trackedCount,
    predicted_demand_D: Math.round(totalDemand * 100) / 100,
    available_vehicles_V: totalIdleVehicles,
    estimated_capacity_C: capacity,
    estimated_shortage: shortage,
    projected_capacity: projectedCapacity,
    pressure_level: pressureLevel,
    pressure_status: pressureStatus,
    repositioning_incoming: totalIncoming,
    active_pickups: totalPickups,
    active_dropoffs: totalDropoffs,
    visual_score: Math.round(visualScore * 100) / 100,
    fillColor,
    fillOpacity,
    center_lat: squareFeature.properties.center_lat,
    center_lng: squareFeature.properties.center_lng
  };
}

export default function ChicagoMapView({ onNavigateToZones }) {
  const [selectedOrigin, setSelectedOrigin] = useState(SAMPLE_ORIGINS[0].id);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [simSpeed, setSimSpeed] = useState(1); // 0.5x, 1x, 2x, 4x
  const [error, setError] = useState(null);
  const [tileWarning, setTileWarning] = useState(false);

  // Authoritative telemetry & simulation state
  const [zoneRecords, setZoneRecords] = useState({});
  const [simState, setSimState] = useState(null);
  const [selectedSquare, setSelectedSquare] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [selectedDriver, setSelectedDriver] = useState(null);
  const [selectedTrip, setSelectedTrip] = useState(null);
  const [dispatchResult, setDispatchResult] = useState(null);
  const [showDispatchModal, setShowDispatchModal] = useState(false);
  const [showEventsDrawer, setShowEventsDrawer] = useState(false);

  // Authoritative Toast Notifications
  const [toasts, setToasts] = useState([]);
  const prevZonePressureRef = useRef(null);
  const seenEventIdsRef = useRef(new Set());

  // UI Panels state
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);

  // Customer ride request creation modal state
  const [showRideModal, setShowRideModal] = useState(false);
  const [ridePickupZone, setRidePickupZone] = useState('882664c1a9fffff');
  const [rideDropoffZone, setRideDropoffZone] = useState('882664c1edfffff');
  const [rideSubmitting, setRideSubmitting] = useState(false);

  // Map layer visibility toggles
  const [showSquareGrid, setShowSquareGrid] = useState(true);
  const [showBoundaries, setShowBoundaries] = useState(false);
  const [showDrivers, setShowDrivers] = useState(true);
  const [showRoutes, setShowRoutes] = useState(true);
  const [showCustomerMarkers, setShowCustomerMarkers] = useState(true);

  // Leaflet map refs & safe in-flight stepping guard
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const squareGridLayerRef = useRef(null);
  const geojsonLayerRef = useRef(null);
  const driversLayerRef = useRef(null);
  const routesLayerRef = useRef(null);
  const customerMarkersLayerRef = useRef(null);
  const playTimerRef = useRef(null);
  const isSteppingRef = useRef(false);
  const resetEpochRef = useRef(0);

  // Auto-dismiss toasts after 5 seconds
  useEffect(() => {
    if (toasts.length === 0) return;
    const interval = setInterval(() => {
      const now = Date.now();
      setToasts((prev) => prev.filter((t) => now - t.createdAt < 5000));
    }, 1000);
    return () => clearInterval(interval);
  }, [toasts.length]);

  const handleDismissToast = useCallback((toastId) => {
    setToasts((prev) => prev.filter((t) => t.id !== toastId));
  }, []);

  // Central state update processor ensuring arrivals & pressure transitions generate toasts
  const processSimulationStateUpdate = useCallback((updatedState) => {
    if (!updatedState) return;

    // 1. Extract arrivals from new recent_events
    const arrivalToasts = extractArrivalToasts(
      updatedState.recent_events || [],
      seenEventIdsRef.current
    );

    // 2. Detect pressure transitions if baseline exists
    let pressureToasts = [];
    if (prevZonePressureRef.current && updatedState.zone_supply) {
      pressureToasts = detectPressureTransitions(
        updatedState.zone_supply,
        prevZonePressureRef.current
      );
    }

    // 3. Update pressure reference baseline
    if (updatedState.zone_supply) {
      prevZonePressureRef.current = { ...updatedState.zone_supply };
    }

    // 4. Enqueue new toasts (keeping at most 4 visible)
    const newToasts = [...arrivalToasts, ...pressureToasts];
    if (newToasts.length > 0) {
      setToasts((prev) => [...prev, ...newToasts].slice(-4));
    }

    setSimState(updatedState);
  }, []);

  // Synchronize selected entities continuously with authoritative simState
  useEffect(() => {
    if (!simState) return;
    if (selectedDriver) {
      const liveD = simState.drivers?.find(d => d.driver_id === selectedDriver.driver_id);
      if (liveD) setSelectedDriver(liveD);
    }
    if (selectedTrip) {
      const liveT = simState.active_trips?.find(t => t.request_id === selectedTrip.request_id);
      setSelectedTrip(liveT || null);
    }
    if (selectedSquare) {
      const squareFeature = (chicagoSquareGrid.features || []).find(
        f => (f.id || f.properties?.grid_id) === selectedSquare.grid_id
      );
      if (squareFeature) {
        const freshAgg = aggregateSquareTelemetry(squareFeature, zoneRecords, simState);
        setSelectedSquare(freshAgg);
      }
    }
    if (selectedZone && simState.zone_supply?.[selectedZone.h3_cell]) {
      const zSupply = simState.zone_supply[selectedZone.h3_cell];
      setSelectedZone(prev => ({
        ...prev,
        available_vehicles_V: zSupply.available_vehicles_V,
        estimated_capacity_C: zSupply.estimated_capacity_C,
        predicted_rides_D: zSupply.predicted_demand_D,
        estimated_unserved_demand_rides: zSupply.estimated_unserved_demand,
        pressure_level: zSupply.pressure_level,
        pressure_status: zSupply.pressure_status,
        repositioning_incoming: zSupply.repositioning_incoming
      }));
    }
  }, [simState]);

  // Load pressure and authoritative simulation state
  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setError(null);

    try {
      const [pressureRes, simRes] = await Promise.all([
        fetchPressure({
          start: selectedOrigin,
          end: selectedOrigin,
          limit: 150
        }),
        fetchSimulationState(selectedOrigin)
      ]);

      const recordsMap = {};
      (pressureRes.data || []).forEach(r => {
        recordsMap[r.h3_cell] = r;
      });
      setZoneRecords(recordsMap);

      // Establish initial baseline without false alerts
      if (!prevZonePressureRef.current && simRes.zone_supply) {
        prevZonePressureRef.current = { ...simRes.zone_supply };
      }
      (simRes.recent_events || []).forEach(e => seenEventIdsRef.current.add(e.event_id));
      setSimState(simRes);

      // Keep inspected entities synced
      if (selectedZone && recordsMap[selectedZone.h3_cell]) {
        setSelectedZone(recordsMap[selectedZone.h3_cell]);
      }
      if (selectedDriver && simRes.drivers) {
        const updatedD = simRes.drivers.find(d => d.driver_id === selectedDriver.driver_id);
        if (updatedD) setSelectedDriver(updatedD);
      }
      if (selectedTrip && simRes.active_trips) {
        const updatedT = simRes.active_trips.find(t => t.request_id === selectedTrip.request_id);
        setSelectedTrip(updatedT || null);
      }
    } catch (err) {
      setError(err?.message || 'Failed to load telemetry and simulation state.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedOrigin, selectedZone, selectedDriver, selectedTrip]);

  useEffect(() => {
    loadData();
  }, [selectedOrigin]); // eslint-disable-line react-hooks/exhaustive-deps

  // Handle Play / Auto-Stepping with safe in-flight request lock & variable speed
  useEffect(() => {
    if (isPlaying) {
      const intervalMs = Math.round(1000 / simSpeed);
      playTimerRef.current = setInterval(async () => {
        if (isSteppingRef.current) return;
        isSteppingRef.current = true;
        const currentEpoch = resetEpochRef.current;
        try {
          const updatedState = await stepSimulation(15);
          if (resetEpochRef.current === currentEpoch) {
            processSimulationStateUpdate(updatedState);
          }
        } catch {
          setIsPlaying(false);
        } finally {
          isSteppingRef.current = false;
        }
      }, intervalMs);
    } else {
      if (playTimerRef.current) clearInterval(playTimerRef.current);
    }

    return () => {
      if (playTimerRef.current) clearInterval(playTimerRef.current);
    };
  }, [isPlaying, simSpeed]);

  // Center/fit map to Chicago operational service area
  const handleFitOperationalBounds = useCallback(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    try {
      // Fit to all 105 square grid features
      const gridLayer = L.geoJSON(chicagoSquareGrid);
      const bounds = gridLayer.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [30, 30], maxZoom: 13 });
      } else {
        map.setView([41.85, -87.68], 11);
      }
    } catch {
      map.setView([41.85, -87.68], 11);
    }
  }, []);

  // Initialize Leaflet Map
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [41.85, -87.68],
      zoom: 11,
      minZoom: 9,
      maxZoom: 16,
      zoomControl: false,
      attributionControl: true
    });

    L.control.zoom({ position: 'bottomleft' }).addTo(map);

    // Read and parse tile configuration from environment
    const rawTilesEnv = (
      import.meta.env.VITE_MAP_TILES_URL ||
      import.meta.env.VITE_CARTO_API_KEY ||
      import.meta.env.VITE_MAP_API_KEY ||
      ''
    ).trim();

    let tileUrl = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    if (rawTilesEnv) {
      if (rawTilesEnv.includes('{z}') && rawTilesEnv.includes('{x}') && rawTilesEnv.includes('{y}')) {
        // Full URL template provided
        tileUrl = rawTilesEnv;
      } else {
        // Bare API key provided: append to CARTO dark matter template
        tileUrl = `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(rawTilesEnv)}`;
      }
    }

    const tileLayer = L.tileLayer(tileUrl, {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noreferrer">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19
    });

    tileLayer.on('tileerror', () => {
      setTileWarning(true);
    });

    tileLayer.addTo(map);

    squareGridLayerRef.current = L.layerGroup().addTo(map);
    geojsonLayerRef.current = L.layerGroup().addTo(map);
    routesLayerRef.current = L.layerGroup().addTo(map);
    driversLayerRef.current = L.layerGroup().addTo(map);
    customerMarkersLayerRef.current = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;

    // Trigger size invalidation and fit bounds after layout render
    const timer = setTimeout(() => {
      map.invalidateSize();
      handleFitOperationalBounds();
    }, 200);

    // ResizeObserver on map container to guarantee correct rendering on panel or viewport changes
    const resizeObserver = new ResizeObserver(() => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.invalidateSize();
      }
    });
    if (mapContainerRef.current) {
      resizeObserver.observe(mapContainerRef.current);
    }

    return () => {
      clearTimeout(timer);
      resizeObserver.disconnect();
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [handleFitOperationalBounds]);

  // 1. Render Square Grid Overlay with Continuous Heatmap Scale
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !squareGridLayerRef.current) return;

    squareGridLayerRef.current.clearLayers();
    if (!showSquareGrid) return;

    const gridGeoLayer = L.geoJSON(chicagoSquareGrid, {
      style: (feature) => {
        const agg = aggregateSquareTelemetry(feature, zoneRecords, simState);
        const isSelected = selectedSquare && selectedSquare.grid_id === agg.grid_id;

        return {
          color: isSelected ? '#38bdf8' : '#334155',
          weight: isSelected ? 2.5 : 1.0,
          fillColor: agg.fillColor,
          fillOpacity: agg.fillOpacity,
          dashArray: isSelected ? '4, 4' : null
        };
      },
      onEachFeature: (feature, layer) => {
        const agg = aggregateSquareTelemetry(feature, zoneRecords, simState);

        const tooltipContent = `
          <div class="font-sans text-xs p-1">
            <div class="font-bold text-slate-100 flex items-center justify-between gap-3">
              <span>${agg.label}</span>
              <span class="text-[10px] font-mono text-cyan-400">Score: ${Math.round(agg.visual_score * 100)}%</span>
            </div>
            <div class="text-[11px] text-slate-300 mt-1 space-y-0.5">
              <div>Predicted Demand (D): <strong class="text-cyan-300">${agg.predicted_demand_D}</strong> rides</div>
              <div>Available Idle (V): <strong class="text-emerald-300">${agg.available_vehicles_V}</strong> | Cap (C): <strong>${agg.estimated_capacity_C}</strong></div>
              <div>Shortage: <strong class="text-rose-400">${agg.estimated_shortage}</strong> rides</div>
              <div>Operational Level: <strong class="text-amber-300">${agg.pressure_level}</strong></div>
              ${agg.repositioning_incoming > 0 ? `<div class="text-sky-300 font-medium">⚡ Incoming: <strong>+${agg.repositioning_incoming}</strong> | Projected Cap: <strong>${agg.projected_capacity}</strong></div>` : ''}
            </div>
          </div>
        `;
        layer.bindTooltip(tooltipContent, {
          sticky: true,
          className: 'custom-leaflet-tooltip'
        });

        layer.on({
          click: () => {
            setSelectedSquare(agg);
            setSelectedZone(null);
            setSelectedDriver(null);
            setSelectedTrip(null);
          },
          mouseover: function () {
            this.setStyle({ weight: 2.2, color: '#38bdf8', fillOpacity: Math.min(0.85, agg.fillOpacity + 0.15) });
          },
          mouseout: function () {
            const isSel = selectedSquare && selectedSquare.grid_id === agg.grid_id;
            this.setStyle({
              color: isSel ? '#38bdf8' : '#334155',
              weight: isSel ? 2.5 : 1.0,
              fillOpacity: agg.fillOpacity
            });
          }
        });
      }
    });

    squareGridLayerRef.current.addLayer(gridGeoLayer);
  }, [zoneRecords, simState, showSquareGrid, selectedSquare]);

  // 2. Render Resolution 8 H3 Zone Outlines
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !geojsonLayerRef.current) return;

    geojsonLayerRef.current.clearLayers();
    if (!showBoundaries) return;

    const hexLayer = L.geoJSON(chicagoH3Zones, {
      style: (feature) => {
        const h3Cell = feature.properties.h3_index;
        const isSelected = selectedZone && selectedZone.h3_cell === h3Cell;
        return {
          color: isSelected ? '#38bdf8' : '#64748b',
          weight: isSelected ? 2.2 : 0.8,
          opacity: 0.6,
          fillColor: 'transparent',
          fillOpacity: 0
        };
      },
      onEachFeature: (feature, layer) => {
        const cell = feature.properties.h3_index;
        const rec = zoneRecords[cell];

        layer.on('click', () => {
          const liveSupply = simState?.zone_supply?.[cell];
          setSelectedZone(liveSupply ? {
            h3_cell: cell,
            predicted_rides_D: liveSupply.predicted_demand_D,
            available_vehicles_V: liveSupply.available_vehicles_V,
            estimated_capacity_C: liveSupply.estimated_capacity_C,
            estimated_shortage: liveSupply.estimated_unserved_demand,
            pressure_level: liveSupply.pressure_level,
            pressure_status: liveSupply.pressure_status,
            repositioning_incoming: liveSupply.repositioning_incoming
          } : (rec || {
            h3_cell: cell,
            predicted_rides_D: 0,
            available_vehicles_V: 0,
            estimated_capacity_C: 0,
            estimated_shortage: 0,
            pressure_level: 'UNTRACKED',
            pressure_status: 'NOT_IN_SNAPSHOT'
          }));
          setSelectedSquare(null);
          setSelectedDriver(null);
          setSelectedTrip(null);
        });
      }
    });

    geojsonLayerRef.current.addLayer(hexLayer);
  }, [zoneRecords, simState, showBoundaries, selectedZone]);

  // 3. Render Simulated Driver Motorcycle Markers & Active Routes
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !driversLayerRef.current || !routesLayerRef.current) return;

    driversLayerRef.current.clearLayers();
    routesLayerRef.current.clearLayers();

    if (!simState || !simState.drivers) return;

    (simState.drivers || []).forEach(driver => {
      // Draw travel routes
      if (showRoutes && driver.target_lat && driver.target_lng && driver.origin_lat && driver.origin_lng) {
        const isCustomerLeg = driver.status === 'WITH_PASSENGER';
        const isReposition = driver.status === 'REPOSITIONING';

        const poly = L.polyline(
          [
            [driver.origin_lat, driver.origin_lng],
            [driver.target_lat, driver.target_lng]
          ],
          {
            color: isCustomerLeg ? '#ef4444' : (isReposition ? '#3b82f6' : '#f59e0b'),
            weight: isCustomerLeg ? 2.5 : 1.8,
            dashArray: isCustomerLeg ? '6, 6' : '3, 6',
            opacity: 0.75
          }
        );
        routesLayerRef.current.addLayer(poly);
      }

      // Draw motorcycle markers
      if (showDrivers) {
        const isSelected = selectedDriver && selectedDriver.driver_id === driver.driver_id;
        const marker = L.marker([driver.lat, driver.lng], {
          icon: createMotorcycleIcon(driver, isSelected),
          zIndexOffset: isSelected ? 1000 : 100
        });

        marker.on('click', () => {
          setSelectedDriver(driver);
          setSelectedSquare(null);
          setSelectedZone(null);
          setSelectedTrip(null);
        });

        driversLayerRef.current.addLayer(marker);
      }
    });
  }, [simState, showDrivers, showRoutes, selectedDriver]);

  // 4. Render Customer Pickup [P] and Dropoff [D] Markers
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !customerMarkersLayerRef.current) return;

    customerMarkersLayerRef.current.clearLayers();
    if (!showCustomerMarkers || !simState || !simState.active_trips) return;

    (simState.active_trips || []).forEach(trip => {
      const isSelected = selectedTrip && selectedTrip.request_id === trip.request_id;

      // Pickup Marker [P]
      if (trip.pickup_lat && trip.pickup_lng) {
        const pickupIcon = L.divIcon({
          html: `<div style="
            width: 22px; height: 22px; border-radius: 9999px; background: #0284c7;
            color: white; font-size: 10px; font-weight: bold; display: flex;
            align-items: center; justify-content: center; border: 2px solid #38bdf8;
            box-shadow: 0 0 8px rgba(56, 189, 248, 0.7); cursor: pointer;
          ">P</div>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11]
        });
        const pMarker = L.marker([trip.pickup_lat, trip.pickup_lng], { icon: pickupIcon });
        pMarker.on('click', () => {
          setSelectedTrip(trip);
          setSelectedSquare(null);
          setSelectedZone(null);
          setSelectedDriver(null);
        });
        customerMarkersLayerRef.current.addLayer(pMarker);
      }

      // Dropoff Marker [D]
      if (trip.dropoff_lat && trip.dropoff_lng) {
        const dropoffIcon = L.divIcon({
          html: `<div style="
            width: 22px; height: 22px; border-radius: 9999px; background: #be123c;
            color: white; font-size: 10px; font-weight: bold; display: flex;
            align-items: center; justify-content: center; border: 2px solid #f43f5e;
            box-shadow: 0 0 8px rgba(244, 63, 94, 0.7); cursor: pointer;
          ">D</div>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11]
        });
        const dMarker = L.marker([trip.dropoff_lat, trip.dropoff_lng], { icon: dropoffIcon });
        dMarker.on('click', () => {
          setSelectedTrip(trip);
          setSelectedSquare(null);
          setSelectedZone(null);
          setSelectedDriver(null);
        });
        customerMarkersLayerRef.current.addLayer(dMarker);
      }
    });
  }, [simState, showCustomerMarkers, selectedTrip]);

  // Operational Simulation Control Actions
  const handlePlayPause = () => setIsPlaying(prev => !prev);

  const handleSingleStep = async () => {
    if (isSteppingRef.current) return;
    isSteppingRef.current = true;
    try {
      const updated = await stepSimulation(15);
      processSimulationStateUpdate(updated);
    } catch (err) {
      setError(err?.message || 'Error stepping simulation clock.');
    } finally {
      isSteppingRef.current = false;
    }
  };

  const handleReset = async () => {
    setIsPlaying(false);
    resetEpochRef.current += 1;
    setToasts([]);
    seenEventIdsRef.current.clear();
    prevZonePressureRef.current = null;
    try {
      const resetState = await resetSimulation(selectedOrigin);
      prevZonePressureRef.current = resetState.zone_supply ? { ...resetState.zone_supply } : null;
      (resetState.recent_events || []).forEach(e => seenEventIdsRef.current.add(e.event_id));
      setSimState(resetState);
      setSelectedDriver(null);
      setSelectedTrip(null);
      setSelectedSquare(null);
      setSelectedZone(null);
      await loadData();
    } catch (err) {
      setError(err?.message || 'Error resetting simulation.');
    }
  };

  const handleOriginChange = async (newOrigin) => {
    setIsPlaying(false);
    resetEpochRef.current += 1;
    setSelectedOrigin(newOrigin);
    setSelectedDriver(null);
    setSelectedTrip(null);
    setSelectedSquare(null);
    setSelectedZone(null);
    setToasts([]);
    seenEventIdsRef.current.clear();
    prevZonePressureRef.current = null;
    try {
      const resetState = await resetSimulation(newOrigin);
      prevZonePressureRef.current = resetState.zone_supply ? { ...resetState.zone_supply } : null;
      (resetState.recent_events || []).forEach(e => seenEventIdsRef.current.add(e.event_id));
      setSimState(resetState);
    } catch (err) {
      console.error('Error changing snapshot origin:', err);
    }
  };

  const handleCloseDispatchModal = () => {
    setShowDispatchModal(false);
    const map = mapInstanceRef.current;
    if (!map) return;

    if (dispatchResult?.assignments?.length > 0) {
      const points = [];
      dispatchResult.assignments.forEach(asgn => {
        const destCoords = getZoneDetails(asgn.destination_zone);
        if (destCoords?.lat && destCoords?.lng) points.push([destCoords.lat, destCoords.lng]);
        const origCoords = getZoneDetails(asgn.origin_zone);
        if (origCoords?.lat && origCoords?.lng) points.push([origCoords.lat, origCoords.lng]);
      });
      if (points.length > 0) {
        try {
          const bounds = L.latLngBounds(points);
          if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
            return;
          }
        } catch {
          // fallback
        }
      }
    }
    handleFitOperationalBounds();
  };

  const handleSpeedChange = (mult) => setSimSpeed(mult);

  const handleRunDispatch = async () => {
    setDispatching(true);
    try {
      const res = await dispatchFleet(selectedOrigin);
      setDispatchResult(res);
      setShowDispatchModal(true);

      // Create dispatch toast within 1 second of response
      const dispatchToast = createDispatchToast(res);
      if (dispatchToast) {
        setToasts((prev) => [...prev, dispatchToast].slice(-4));
      }

      const updatedState = await fetchSimulationState(selectedOrigin);
      processSimulationStateUpdate(updatedState);
    } catch (err) {
      setError(err?.message || 'Error executing automated dispatch.');
    } finally {
      setDispatching(false);
    }
  };

  const handleCreateRide = async (e) => {
    e.preventDefault();
    setRideSubmitting(true);
    try {
      const pDetails = getZoneDetails(ridePickupZone);
      const dDetails = getZoneDetails(rideDropoffZone);

      await createCustomerRequest({
        pickup_h3_cell: ridePickupZone,
        dropoff_h3_cell: rideDropoffZone,
        pickup_lat: pDetails.lat,
        pickup_lng: pDetails.lng,
        dropoff_lat: dDetails.lat,
        dropoff_lng: dDetails.lng
      });

      setShowRideModal(false);
      const updated = await fetchSimulationState(selectedOrigin);
      setSimState(updated);
    } catch (err) {
      setError(err?.message || 'Failed to dispatch customer ride request.');
    } finally {
      setRideSubmitting(false);
    }
  };

  const handleCancelTrip = async (tripId) => {
    try {
      await cancelCustomerRequest(tripId);
      setSelectedTrip(null);
      const updated = await fetchSimulationState(selectedOrigin);
      setSimState(updated);
    } catch (err) {
      setError(err?.message || 'Error canceling customer trip.');
    }
  };

  // Fleet Summary metrics computed from authoritative simState
  const fleetSummary = useMemo(() => {
    const drivers = simState?.drivers || [];
    return {
      total: drivers.length,
      idle: drivers.filter(d => d.status === 'IDLE').length,
      repositioning: drivers.filter(d => d.status === 'REPOSITIONING').length,
      to_pickup: drivers.filter(d => d.status === 'TO_PICKUP').length,
      with_passenger: drivers.filter(d => d.status === 'WITH_PASSENGER').length,
      off_duty: drivers.filter(d => d.status === 'OFF_DUTY').length
    };
  }, [simState]);

  const activeTripsCount = simState?.active_trips?.length || 0;
  const recentEvents = simState?.recent_events || [];
  const latestEvent = recentEvents[recentEvents.length - 1];
  const allZonesList = useMemo(() => getAllZoneLabels(), []);

  return (
    <div className="relative w-full h-full overflow-hidden select-none bg-slate-950 font-sans text-slate-100">
      {/* 1. Main Interactive Map Container */}
      <div
        ref={mapContainerRef}
        className="absolute inset-0 w-full h-full z-0 bg-[#0b0f19] cursor-grab active:cursor-grabbing"
      />

      {/* Non-intrusive Map Tile Warning Banner if tiles fail to load */}
      {tileWarning && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1002] bg-slate-900/90 border border-amber-500/50 text-amber-300 text-xs px-3 py-1.5 rounded-full shadow-lg flex items-center gap-2 backdrop-blur-md">
          <AlertTriangle size={14} className="text-amber-400" />
          <span>Notice: Tile layer connection issue. Falling back to dark canvas. Vector overlays are operational.</span>
          <button onClick={() => setTileWarning(false)} className="hover:text-white cursor-pointer ml-1">✕</button>
        </div>
      )}

      {/* 2. Left Floating Panel: Simulation Controls & Live KPIs */}
      <div className={`absolute top-3 left-3 z-[1000] w-80 max-w-[calc(100vw-24px)] flex flex-col gap-2 transition-all duration-200 ${leftPanelCollapsed ? 'max-h-12 overflow-hidden' : ''}`}>
        <div className="bg-slate-950/85 backdrop-blur-md border border-slate-800/90 rounded-xl shadow-2xl p-3.5 space-y-3">
          {/* Panel Header */}
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
              <h1 className="text-xs font-bold uppercase tracking-wider text-slate-100">
                Command Centre
              </h1>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={loadData}
                disabled={refreshing}
                title="Refresh Telemetry"
                className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition cursor-pointer"
              >
                <RefreshCw size={13} className={refreshing ? 'animate-spin text-cyan-400' : ''} />
              </button>
              <button
                onClick={() => setLeftPanelCollapsed(!leftPanelCollapsed)}
                title={leftPanelCollapsed ? 'Expand Panel' : 'Collapse Panel'}
                className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition cursor-pointer"
              >
                {leftPanelCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </button>
            </div>
          </div>

          {!leftPanelCollapsed && (
            <>
              {/* Snapshot Origin Selector */}
              <div>
                <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
                  Forecast Snapshot Origin (CDT)
                </label>
                <select
                  value={selectedOrigin}
                  onChange={(e) => handleOriginChange(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700/80 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                >
                  {SAMPLE_ORIGINS.map((orig) => (
                    <option key={orig.id} value={orig.id}>
                      {orig.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Authoritative Simulation Clock */}
              <div className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 flex items-center justify-between text-xs">
                <div>
                  <div className="text-[10px] uppercase font-bold text-slate-400">Simulation Clock</div>
                  <div className="text-xs font-bold text-cyan-400 font-mono mt-0.5">
                    {simState ? formatChicagoTime(simState.simulation_time || simState.current_sim_time) : '—'}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] uppercase font-bold text-slate-400">Clock Tick</div>
                  <div className="text-xs font-mono text-slate-300">
                    #{simState?.clock_tick || 0}
                  </div>
                </div>
              </div>

              {/* Playback Controls & Speed Multipliers */}
              <div className="space-y-2">
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={handlePlayPause}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
                      isPlaying
                        ? 'bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-950/50'
                        : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-950/50'
                    }`}
                  >
                    {isPlaying ? <Pause size={13} /> : <Play size={13} />}
                    <span>{isPlaying ? 'Pause' : 'Play Live'}</span>
                  </button>

                  <button
                    onClick={handleSingleStep}
                    disabled={isPlaying}
                    title="Advance simulation by 15 seconds"
                    className="flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold disabled:opacity-40 transition cursor-pointer"
                  >
                    <FastForward size={13} />
                    <span>Step</span>
                  </button>

                  <button
                    onClick={handleReset}
                    title="Reset deterministic simulation"
                    className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition cursor-pointer"
                  >
                    <RotateCcw size={13} />
                  </button>
                </div>

                {/* Speed Multipliers */}
                <div className="flex items-center justify-between gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800">
                  <span className="text-[10px] font-semibold text-slate-400 pl-1.5">Speed:</span>
                  <div className="flex items-center gap-1">
                    {[0.5, 1, 2, 4].map((mult) => (
                      <button
                        key={mult}
                        onClick={() => handleSpeedChange(mult)}
                        className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold transition cursor-pointer ${
                          simSpeed === mult
                            ? 'bg-cyan-600 text-white shadow-sm'
                            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                        }`}
                      >
                        {mult}x
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Action Buttons: Dispatch & Customer Request */}
              <div className="flex items-center gap-2 pt-1 border-t border-slate-800/80">
                <button
                  onClick={handleRunDispatch}
                  disabled={dispatching}
                  className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-cyan-600/90 hover:bg-cyan-500 text-white text-xs font-bold transition cursor-pointer disabled:opacity-50"
                  title="Execute dynamic repositioning toward forecast deficits"
                >
                  <Navigation size={12} className={dispatching ? 'animate-spin' : ''} />
                  <span>{dispatching ? 'Dispatching...' : 'Update Status'}</span>
                </button>

                <button
                  onClick={() => setShowRideModal(true)}
                  className="flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600/90 hover:bg-emerald-500 text-white text-xs font-bold transition cursor-pointer"
                  title="Simulate customer ride pickup and dropoff request"
                >
                  <PhoneCall size={12} />
                  <span>Ride</span>
                </button>
              </div>

              {/* Compact Live Fleet KPIs Grid */}
              <div className="grid grid-cols-2 gap-1.5 text-xs pt-1 border-t border-slate-800/80">
                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block font-medium">Idle Supply</span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-bold text-emerald-400 text-sm font-mono">{fleetSummary.idle}</span>
                    <span className="text-[10px] text-slate-400">/ {fleetSummary.total} fleet</span>
                  </div>
                </div>

                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block font-medium">In Transit</span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-bold text-sky-400 text-sm font-mono">
                      {fleetSummary.repositioning + fleetSummary.to_pickup + fleetSummary.with_passenger}
                    </span>
                    <span className="text-[10px] text-slate-400">moving</span>
                  </div>
                </div>

                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block font-medium">Active Trips</span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-bold text-amber-400 text-sm font-mono">{activeTripsCount}</span>
                    <span className="text-[10px] text-slate-400">in-flight</span>
                  </div>
                </div>

                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-400 block font-medium">Completed</span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-bold text-emerald-400 text-sm font-mono">
                      {simState?.completed_trips_count || 0}
                    </span>
                    <span className="text-[10px] text-slate-400">served</span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 3. Top-Right Floating Panel: Layer Toggles & Heatmap / Vehicle Legend */}
      <div className={`absolute top-3 right-3 z-[1000] w-72 max-w-[calc(100vw-24px)] flex flex-col gap-2 transition-all duration-200 ${rightPanelCollapsed ? 'max-h-12 overflow-hidden' : ''}`}>
        <div className="bg-slate-950/85 backdrop-blur-md border border-slate-800/90 rounded-xl shadow-2xl p-3 space-y-3">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-1.5">
            <div className="flex items-center gap-1.5 text-xs font-bold uppercase text-slate-200">
              <Layers size={13} className="text-cyan-400" />
              <span>Layers &amp; Legend</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={handleFitOperationalBounds}
                title="Fit Chicago Operational Bounds"
                className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition cursor-pointer"
              >
                <Compass size={13} />
              </button>
              <button
                onClick={() => setRightPanelCollapsed(!rightPanelCollapsed)}
                title={rightPanelCollapsed ? 'Expand Panel' : 'Collapse Panel'}
                className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition cursor-pointer"
              >
                {rightPanelCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </button>
            </div>
          </div>

          {!rightPanelCollapsed && (
            <>
              {/* Layer Toggles */}
              <div className="space-y-1.5 text-xs">
                <label className="flex items-center justify-between p-1 rounded hover:bg-slate-900/60 cursor-pointer">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <Grid size={13} className="text-cyan-400" />
                    <span>Square Grid (Aggregated Heatmap)</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={showSquareGrid}
                    onChange={(e) => setShowSquareGrid(e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                </label>

                <label className="flex items-center justify-between p-1 rounded hover:bg-slate-900/60 cursor-pointer">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <Layers size={13} className="text-indigo-400" />
                    <span>H3 Zone Hexagons (Constituent)</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={showBoundaries}
                    onChange={(e) => setShowBoundaries(e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                </label>

                {/* Spatial Hierarchy Note */}
                <div className="p-2 rounded bg-slate-900/90 border border-slate-800 text-[10px] text-slate-400 leading-tight">
                  <span className="text-cyan-300 font-semibold block mb-0.5">Spatial Hierarchy:</span>
                  The primary heatmap uses 105 square grid cells, aggregating 1–4 underlying H3 Res 8 zones (~0.73 km² each) to present an intuitive continuous citywide surface. Toggle H3 Hexagons to inspect granular polygon boundaries.
                </div>

                <label className="flex items-center justify-between p-1 rounded hover:bg-slate-900/60 cursor-pointer">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <Car size={13} className="text-emerald-400" />
                    <span>Rider Markers (60)</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={showDrivers}
                    onChange={(e) => setShowDrivers(e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                </label>

                <label className="flex items-center justify-between p-1 rounded hover:bg-slate-900/60 cursor-pointer">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <Navigation size={13} className="text-purple-400" />
                    <span>Routes &amp; Trajectories</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={showRoutes}
                    onChange={(e) => setShowRoutes(e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                </label>

                <label className="flex items-center justify-between p-1 rounded hover:bg-slate-900/60 cursor-pointer">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <MapPin size={13} className="text-rose-400" />
                    <span>Pickups &amp; Dropoffs</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={showCustomerMarkers}
                    onChange={(e) => setShowCustomerMarkers(e.target.checked)}
                    className="accent-cyan-500 rounded"
                  />
                </label>
              </div>

              {/* Heatmap Visual Scale (Continuous: Teal -> Green -> Yellow -> Orange -> Red) */}
              <div className="border-t border-slate-800/80 pt-2 space-y-1.5">
                <div className="flex items-center justify-between text-[11px] font-semibold text-slate-200">
                  <span className="flex items-center gap-1">
                    <Flame size={12} className="text-amber-400" />
                    <span>Heatmap Intensity Scale</span>
                  </span>
                  <span className="text-[10px] text-cyan-400 font-mono">Continuous</span>
                </div>

                {/* Continuous visual gradient bar */}
                <div
                  className="w-full h-3 rounded-full border border-slate-700/80 shadow-inner"
                  style={{
                    background: 'linear-gradient(to right, #0f766e 0%, #10b981 25%, #eab308 50%, #f97316 75%, #ef4444 100%)'
                  }}
                />
                <div className="flex justify-between text-[9px] text-slate-400 font-medium">
                  <span>Minimal</span>
                  <span>Balanced</span>
                  <span>Moderate</span>
                  <span>High</span>
                  <span className="text-rose-400 font-bold">Surge Core</span>
                </div>
                <p className="text-[9px] text-slate-400 leading-tight">
                  Smooth visual intensity based on localized demand &amp; capacity deficit. Authoritative operational metrics (D, V, C) are listed separately per zone.
                </p>
              </div>

              {/* Motorcycle Rider Status Legend */}
              <div className="border-t border-slate-800/80 pt-2 space-y-1 text-[10px]">
                <div className="font-semibold text-slate-200 text-[11px] mb-1">Rider Fleet Status</div>
                <div className="grid grid-cols-2 gap-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                    <span className="text-slate-300">Idle ({fleetSummary.idle})</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                    <span className="text-slate-300">Reposition ({fleetSummary.repositioning})</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                    <span className="text-slate-300">To Pickup ({fleetSummary.to_pickup})</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
                    <span className="text-slate-300">Passenger ({fleetSummary.with_passenger})</span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Command Centre Simulation Notification Feed */}
      <SimulationToastContainer
        toasts={toasts}
        onDismiss={handleDismissToast}
        hasInspectorOpen={Boolean(selectedSquare || selectedZone || selectedDriver || selectedTrip)}
      />

      {/* 4. Bottom-Right Floating Inspector (Selected Square, Driver, or Trip Details) */}
      {(selectedSquare || selectedZone || selectedDriver || selectedTrip) && (
        <div className="absolute bottom-12 right-3 z-[1000] w-84 max-w-[calc(100vw-24px)] max-h-[calc(100vh-160px)] overflow-y-auto">
          <div className="bg-slate-950/90 backdrop-blur-md border border-slate-800 rounded-xl shadow-2xl p-3.5 space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <div className="text-xs font-bold uppercase text-slate-200">
                {selectedSquare && 'Square Grid Inspector'}
                {selectedZone && 'H3 Zone Telemetry'}
                {selectedDriver && 'Driver Telemetry'}
                {selectedTrip && 'Customer Trip Details'}
              </div>
              <button
                onClick={() => {
                  setSelectedSquare(null);
                  setSelectedZone(null);
                  setSelectedDriver(null);
                  setSelectedTrip(null);
                }}
                className="text-slate-400 hover:text-white cursor-pointer"
              >
                <X size={14} />
              </button>
            </div>

            {/* Selected Square Details */}
            {selectedSquare && (
              <div className="space-y-2 text-xs">
                <div>
                  <h3 className="font-bold text-slate-100 text-sm">{selectedSquare.label}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <Badge variant={selectedSquare.pressure_level || 'LOW'}>
                      {selectedSquare.pressure_level}
                    </Badge>
                    <span className="text-[10px] text-cyan-400 font-mono">
                      Visual Score: {Math.round(selectedSquare.visual_score * 100)}%
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <div>
                    <span className="text-[10px] text-slate-400 block">Predicted Demand (D)</span>
                    <span className="font-bold text-cyan-400 font-mono text-sm">
                      {selectedSquare.predicted_demand_D}
                    </span>
                    <span className="text-[9px] text-slate-500 block">rides / 30m</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Idle Vehicles (V)</span>
                    <span className="font-bold text-emerald-400 font-mono text-sm">
                      {selectedSquare.available_vehicles_V}
                    </span>
                    <span className="text-[9px] text-slate-500 block">Capacity C: {selectedSquare.estimated_capacity_C}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Expected Shortage</span>
                    <span className="font-bold text-rose-400 font-mono text-sm">
                      {selectedSquare.estimated_shortage}
                    </span>
                    <span className="text-[9px] text-slate-500 block">rides deficit</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Constituent Cells</span>
                    <span className="font-bold text-slate-200 font-mono text-sm">
                      {selectedSquare.h3_count}
                    </span>
                    <span className="text-[9px] text-slate-500 block">H3 Resolution 8</span>
                  </div>
                </div>

                {selectedSquare.repositioning_incoming > 0 && (
                  <div className="p-2 rounded bg-sky-950/40 border border-sky-800/60 text-sky-300 text-[11px] flex items-center gap-2">
                    <Navigation size={13} />
                    <span>{selectedSquare.repositioning_incoming} vehicle(s) dispatched toward this zone.</span>
                  </div>
                )}
              </div>
            )}

            {/* Selected Driver Details */}
            {selectedDriver && (
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-bold text-slate-100 text-sm">{selectedDriver.name}</h3>
                    <div className="text-[11px] font-mono text-slate-400">{selectedDriver.driver_id}</div>
                  </div>
                  <span
                    className="px-2 py-0.5 rounded text-[10px] font-bold"
                    style={{
                      backgroundColor: `${DRIVER_STATUS_COLORS[selectedDriver.status]}25`,
                      color: DRIVER_STATUS_COLORS[selectedDriver.status],
                      border: `1px solid ${DRIVER_STATUS_COLORS[selectedDriver.status]}55`
                    }}
                  >
                    {selectedDriver.status}
                  </span>
                </div>

                <div className="space-y-1.5 p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Current Zone:</span>
                    <span className="font-mono text-slate-200">{getZoneLabel(selectedDriver.current_h3_cell)}</span>
                  </div>
                  {selectedDriver.destination_h3_cell && (
                    <div className="flex justify-between">
                      <span className="text-slate-400">Destination:</span>
                      <span className="font-mono text-cyan-300 font-semibold">{getZoneLabel(selectedDriver.destination_h3_cell)}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-slate-400">Speed / Travel ETA:</span>
                    <span className="font-mono text-slate-200">{selectedDriver.speed_kmh} km/h &bull; {selectedDriver.eta_seconds || 0}s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Completed Trips:</span>
                    <span className="font-mono text-emerald-400 font-bold">{selectedDriver.completed_trips_count}</span>
                  </div>
                </div>

                {selectedDriver.route_progress > 0 && selectedDriver.route_progress < 1 && (
                  <div>
                    <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                      <span>Trip Progress</span>
                      <span>{Math.round(selectedDriver.route_progress * 100)}%</span>
                    </div>
                    <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                      <div
                        className="bg-cyan-500 h-full rounded-full transition-all duration-300"
                        style={{ width: `${Math.round(selectedDriver.route_progress * 100)}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Selected Trip Details */}
            {selectedTrip && (
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-bold text-slate-100">{selectedTrip.request_id}</h3>
                    <div className="text-[10px] text-slate-400">Customer Trip</div>
                  </div>
                  <Badge variant={selectedTrip.status}>
                    {selectedTrip.status}
                  </Badge>
                </div>

                <div className="space-y-1 p-2 rounded-lg bg-slate-900 border border-slate-800">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Pickup:</span>
                    <span className="font-mono text-cyan-300">{getZoneLabel(selectedTrip.pickup_h3_cell)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Dropoff:</span>
                    <span className="font-mono text-amber-300">{getZoneLabel(selectedTrip.dropoff_h3_cell)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Assigned Driver:</span>
                    <span className="font-mono text-slate-200 font-semibold">{selectedTrip.assigned_driver_id || 'Awaiting dispatch'}</span>
                  </div>
                </div>

                {selectedTrip.status !== 'COMPLETED' && selectedTrip.status !== 'CANCELLED' && (
                  <button
                    onClick={() => handleCancelTrip(selectedTrip.request_id)}
                    className="w-full py-1.5 rounded bg-rose-900/60 hover:bg-rose-800 text-rose-200 text-xs font-semibold border border-rose-700/60 transition cursor-pointer"
                  >
                    Cancel Customer Request
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 5. Bottom Live Simulation Event Strip & Drawer Trigger */}
      <div className="absolute bottom-0 left-0 right-0 z-[1000] h-9 bg-slate-950/90 backdrop-blur-md border-t border-slate-800/80 px-4 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 overflow-hidden mr-4">
          <Activity size={13} className="text-cyan-400 shrink-0" />
          <span className="text-[10px] uppercase font-bold text-slate-400 shrink-0">Live Event:</span>
          {latestEvent ? (
            <span className="text-xs text-slate-300 truncate font-mono">
              <span className="text-cyan-400">[{latestEvent.event_type}]</span> {latestEvent.message}
            </span>
          ) : (
            <span className="text-xs text-slate-500 font-mono">Telemetry idle. Ready for dispatch operations.</span>
          )}
        </div>

        <button
          onClick={() => setShowEventsDrawer(!showEventsDrawer)}
          className="text-xs text-cyan-400 hover:text-cyan-300 font-semibold shrink-0 cursor-pointer flex items-center gap-1"
        >
          <span>Feed ({recentEvents.length})</span>
          {showEventsDrawer ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
        </button>
      </div>

      {/* Expandable Recent Events Drawer */}
      {showEventsDrawer && (
        <div className="absolute bottom-9 left-0 right-0 z-[999] max-h-56 bg-slate-950/95 backdrop-blur-md border-t border-slate-800 overflow-y-auto p-4 space-y-2">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">
              Authoritative Event Audit Stream ({recentEvents.length} events)
            </h4>
            <button
              onClick={() => setShowEventsDrawer(false)}
              className="text-slate-400 hover:text-white cursor-pointer text-xs"
            >
              ✕ Close
            </button>
          </div>

          <div className="space-y-1.5">
            {recentEvents.slice().reverse().map((evt, idx) => (
              <div key={idx} className="p-2 rounded bg-slate-900 border border-slate-800/80 flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 text-[10px]">{evt.sim_time ? formatChicagoTime(evt.sim_time) : `Tick #${evt.clock_tick}`}</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">
                    {evt.event_type}
                  </span>
                  <span className="text-slate-300">{evt.message}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* MODAL: Dispatch Results */}
      {showDispatchModal && dispatchResult && (
        <div className="fixed inset-0 z-[2000] bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={18} className="text-emerald-400" />
                <h3 className="text-base font-bold text-slate-100">Authoritative Dispatch Executed</h3>
              </div>
              <button
                onClick={handleCloseDispatchModal}
                className="text-slate-400 hover:text-slate-200 cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            {dispatchResult.explanation ? (
              <div className="p-2.5 rounded-lg bg-cyan-950/40 border border-cyan-800/60 text-cyan-200 text-xs">
                {dispatchResult.explanation}
              </div>
            ) : (
              <p className="text-xs text-slate-300">
                The backend dispatch algorithm evaluated idle surplus drivers against XGBoost forecast deficit hotspots while strictly protecting origin coverage floors.
              </p>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block text-[10px]">Drivers Evaluated</span>
                <span className="font-bold text-slate-100 text-sm">{dispatchResult.drivers_considered}</span>
              </div>
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block text-[10px]">Drivers Dispatched</span>
                <span className="font-bold text-cyan-400 text-sm">+{dispatchResult.drivers_assigned}</span>
              </div>
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block text-[10px]">Retained for Coverage</span>
                <span className="font-bold text-emerald-400 text-sm">{dispatchResult.drivers_retained_coverage}</span>
              </div>
              <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                <span className="text-slate-400 block text-[10px]">Deficit Hotspots</span>
                <span className="font-bold text-amber-400 text-sm">{dispatchResult.underserved_zones_before} &rarr; {dispatchResult.underserved_zones_after}</span>
              </div>
            </div>

            {dispatchResult.skipped_reasons && Object.keys(dispatchResult.skipped_reasons).length > 0 && (
              <div className="space-y-1.5 pt-1 text-xs">
                <div className="text-[10px] font-bold uppercase text-slate-400">Target Hotspots Unassigned Reasons</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(dispatchResult.skipped_reasons).map(([reason, count]) => (
                    <span key={reason} className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300 text-[10px] font-mono">
                      {reason}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="flex justify-end pt-2 border-t border-slate-800">
              <button
                onClick={handleCloseDispatchModal}
                className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold cursor-pointer"
              >
                Close &amp; View Map
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Customer Ride Request Simulation */}
      {showRideModal && (
        <div className="fixed inset-0 z-[2000] bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <form onSubmit={handleCreateRide} className="bg-slate-900 border border-slate-700 rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <PhoneCall size={18} className="text-emerald-400" />
                <h3 className="text-base font-bold text-slate-100">Simulate Passenger Ride Request</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowRideModal(false)}
                className="text-slate-400 hover:text-slate-200 cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-300">
              Select pickup and dropoff zones from Chicago catalog cells. The authoritative simulation engine will match the closest eligible IDLE driver.
            </p>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-semibold">Pickup Origin Zone</label>
                <select
                  value={ridePickupZone}
                  onChange={(e) => setRidePickupZone(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg p-2.5 focus:border-cyan-500 focus:outline-none"
                >
                  {allZonesList.map(z => (
                    <option key={z.id} value={z.id}>
                      {z.label} ({z.id.slice(0, 8)}...)
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-semibold">Dropoff Destination Zone</label>
                <select
                  value={rideDropoffZone}
                  onChange={(e) => setRideDropoffZone(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg p-2.5 focus:border-cyan-500 focus:outline-none"
                >
                  {allZonesList.map(z => (
                    <option key={z.id} value={z.id}>
                      {z.label} ({z.id.slice(0, 8)}...)
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setShowRideModal(false)}
                className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={rideSubmitting}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-pointer disabled:opacity-50"
              >
                {rideSubmitting ? 'Dispatching...' : 'Confirm Request'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
