import React, { useState, useEffect, useCallback } from 'react';
import { fetchPressure, formatChicagoTime } from '../services/api';
import { getZoneLabel } from '../services/zoneLabels';
import Badge from '../components/Badge';
import { LoadingState, ErrorState, EmptyState } from '../components/States';
import {
  Copy,
  Check,
  Filter,
  ChevronLeft,
  ChevronRight,
  Info
} from 'lucide-react';

const PRESSURE_LEVELS = [
  { id: '', label: 'All Levels' },
  { id: 'CRITICAL', label: 'Critical' },
  { id: 'HIGH', label: 'High' },
  { id: 'MODERATE', label: 'Moderate' },
  { id: 'NO_CAPACITY', label: 'No Capacity (C=0)' },
  { id: 'LOW', label: 'Low / Normal' },
];

export default function ZoneIntelligenceView() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [records, setRecords] = useState([]);
  const [totalRecords, setTotalRecords] = useState(0);

  // Filters
  const [selectedZone, setSelectedZone] = useState('');
  const [selectedLevel, setSelectedLevel] = useState('');
  const [pageOffset, setPageOffset] = useState(0);
  const pageSize = 25;

  // Metadata / zone options
  const [operationalZones, setOperationalZones] = useState([]);
  const [copiedZone, setCopiedZone] = useState(null);

  useEffect(() => {
    async function loadZoneCatalog() {
      try {
        const res = await fetchPressure({ limit: 135 });
        const uniqueZones = Array.from(new Set(res.data.map(d => d.h3_cell))).sort();
        setOperationalZones(uniqueZones);
      } catch {
        // Fallback
      }
    }
    loadZoneCatalog();
  }, []);

  const loadPressureData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchPressure({
        zone: selectedZone || undefined,
        pressure_level: selectedLevel || undefined,
        limit: pageSize,
        offset: pageOffset
      });
      setRecords(res.data || []);
      setTotalRecords(res.total_records || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedZone, selectedLevel, pageOffset, pageSize]);

  useEffect(() => {
    loadPressureData();
  }, [loadPressureData]);

  function handleCopy(h3Cell) {
    navigator.clipboard.writeText(h3Cell);
    setCopiedZone(h3Cell);
    setTimeout(() => setCopiedZone(null), 2000);
  }

  const totalPages = Math.ceil(totalRecords / pageSize);
  const currentPage = Math.floor(pageOffset / pageSize) + 1;

  return (
    <div className="space-y-6">
      {/* Filters & Zone Selector Toolbar */}
      <div className="p-5 rounded-xl bg-slate-900/90 border border-slate-800 shadow-sm flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
        <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
          {/* Zone Selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Zone:
            </span>
            <select
              value={selectedZone}
              onChange={(e) => {
                setSelectedZone(e.target.value);
                setPageOffset(0);
              }}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 focus:border-cyan-500 focus:outline-none cursor-pointer max-w-xs md:max-w-sm"
            >
              <option value="">All Operational Zones ({operationalZones.length || 135})</option>
              {operationalZones.map(z => (
                <option key={z} value={z}>{getZoneLabel(z)} &mdash; {z.slice(0, 10)}...</option>
              ))}
            </select>
          </div>

          {/* Pressure Level Filter */}
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-slate-400" />
            <select
              value={selectedLevel}
              onChange={(e) => {
                setSelectedLevel(e.target.value);
                setPageOffset(0);
              }}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 focus:border-cyan-500 focus:outline-none cursor-pointer"
            >
              {PRESSURE_LEVELS.map(lvl => (
                <option key={lvl.id} value={lvl.id}>{lvl.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Total Count Indicator */}
        <div className="text-xs text-slate-400">
          {loading ? (
            <span className="text-slate-500 italic">Loading records...</span>
          ) : error ? (
            <span className="text-rose-400">Unable to load records</span>
          ) : (
            <>
              Showing <span className="font-semibold text-slate-200">{records.length}</span> of{' '}
              <span className="font-semibold text-slate-200">{totalRecords.toLocaleString()}</span> records
            </>
          )}
        </div>
      </div>

      {/* Notices Grid: H3 Governance, NO_CAPACITY Explanation, and Operational Pressure vs Surge Alerts */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Geometry Disclosure Notice */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-start gap-3 text-xs text-slate-400">
          <Info size={16} className="text-cyan-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-slate-200 block mb-0.5">H3 Resolution 8 Governance:</span>
            Forecasts and simulated supply are indexed at Resolution 8 hexagons (~0.73 km²). Raw Chicago taxi coordinates were anonymized to community areas in source records. Telemetry is displayed honestly in tabular format without synthetic polygon interpolation.
          </div>
        </div>

        {/* NO_CAPACITY Clarification Notice */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-start gap-3 text-xs text-slate-400">
          <Info size={16} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-slate-200 block mb-0.5">NO_CAPACITY (Zero Estimated Supply):</span>
            When the multinomial simulation allocates 0 available vehicles ($V=0$) to a peripheral zone where the ML model predicts micro-demand ($D &gt; 0$), status is NO_CAPACITY. This is a simulated supply estimate, not real-time GPS driver absence.
          </div>
        </div>

        {/* Pressure Level vs Surge Alerts Notice */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-start gap-3 text-xs text-slate-400">
          <Info size={16} className="text-indigo-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-slate-200 block mb-0.5">Operational Pressure vs. Surge Alerts:</span>
            Zone Intelligence reflects base operational pressure (<span className="font-mono">P = D / C</span>) for all 135 operational zones. In contrast, the Surge Alerts feed applies multi-factor eligibility criteria: minimum demand (<span className="font-mono">D &ge; 5.0</span> rides), elevated pressure (<span className="font-mono">P &ge; 1.20</span>), and verified baseline demand growth (<span className="font-mono">D / baseline &ge; 1.30</span>). Peripheral zones classified as Critical or No Capacity do not trigger surge alerts unless they satisfy these criteria.
          </div>
        </div>
      </div>

      {/* Main Table Card */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        {loading ? (
          <LoadingState message="Fetching zone pressure telemetry..." />
        ) : error ? (
          <div className="p-6">
            <ErrorState message={error} onRetry={loadPressureData} />
          </div>
        ) : records.length === 0 ? (
          <div className="p-6">
            <EmptyState message="No pressure records found matching the selected zone or level filter." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/80 border-b border-slate-800 text-slate-400">
                <tr>
                  <th className="py-3 px-4 font-semibold">Zone (Label &amp; H3 Hex)</th>
                  <th className="py-3 px-4 font-semibold">Forecast Origin (Local)</th>
                  <th className="py-3 px-4 font-semibold text-right">Predicted Demand (D)</th>
                  <th className="py-3 px-4 font-semibold text-right">Vehicles (V)</th>
                  <th className="py-3 px-4 font-semibold text-right">Capacity (C)</th>
                  <th className="py-3 px-4 font-semibold text-center">Pressure Ratio (P)</th>
                  <th className="py-3 px-4 font-semibold text-right">Unserved Demand</th>
                  <th className="py-3 px-4 font-semibold text-center">Pressure Level</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans">
                {records.map((r, i) => {
                  const label = getZoneLabel(r.h3_cell);
                  return (
                    <tr key={i} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <div>
                            <span className="font-bold text-slate-100 block">{label}</span>
                            <span className="text-[11px] text-slate-400 font-mono">{r.h3_cell.slice(0, 10)}...</span>
                          </div>
                          <button
                            onClick={() => handleCopy(r.h3_cell)}
                            title={`Copy full H3 cell: ${r.h3_cell}`}
                            className="text-slate-500 hover:text-cyan-400 transition cursor-pointer p-1 rounded"
                          >
                            {copiedZone === r.h3_cell ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                          </button>
                        </div>
                      </td>
                      <td className="py-3 px-4 text-slate-300">
                        {formatChicagoTime(r.forecast_origin)}
                      </td>
                      <td className="py-3 px-4 text-right font-medium text-cyan-400">
                        {r.predicted_rides_D?.toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-300">
                        {r.available_vehicles_V}
                      </td>
                      <td className="py-3 px-4 text-right font-medium text-indigo-400">
                        {r.estimated_capacity_C?.toFixed(1)}
                      </td>
                      <td className="py-3 px-4 text-center font-bold text-slate-100">
                        {typeof r.pressure_index === 'number' ? (
                          r.pressure_index.toFixed(2)
                        ) : (
                          <div className="text-slate-400 text-[11px] font-normal">
                            <span className="italic font-mono">null</span>
                            <span className="block text-[10px] text-slate-500 font-sans">C = 0</span>
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right text-slate-300 font-medium">
                        {(r.estimated_unserved_demand_rides || 0).toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <Badge value={r.pressure_level} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Bar */}
        {!loading && totalRecords > pageSize && (
          <div className="p-4 border-t border-slate-800 bg-slate-950/40 flex items-center justify-between text-xs text-slate-400">
            <div>
              Page <span className="font-semibold text-slate-200">{currentPage}</span> of{' '}
              <span className="font-semibold text-slate-200">{totalPages}</span>
            </div>

            <div className="flex items-center gap-2">
              <button
                disabled={pageOffset === 0}
                onClick={() => setPageOffset(Math.max(0, pageOffset - pageSize))}
                className="px-3 py-1.5 rounded-lg border border-slate-800 hover:bg-slate-800/80 disabled:opacity-40 disabled:hover:bg-transparent text-slate-300 transition flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
              >
                <ChevronLeft size={14} /> Previous
              </button>
              <button
                disabled={pageOffset + pageSize >= totalRecords}
                onClick={() => setPageOffset(pageOffset + pageSize)}
                className="px-3 py-1.5 rounded-lg border border-slate-800 hover:bg-slate-800/80 disabled:opacity-40 disabled:hover:bg-transparent text-slate-300 transition flex items-center gap-1 cursor-pointer disabled:cursor-not-allowed"
              >
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
