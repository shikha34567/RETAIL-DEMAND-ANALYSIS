import React, { useEffect, useState, useCallback } from 'react';
import {
  fetchPressure,
  fetchSurgeAlerts,
  formatChicagoTime
} from '../services/api';
import { getZoneLabel, getZoneDetails } from '../services/zoneLabels';
import StatCard from '../components/StatCard';
import Badge from '../components/Badge';
import { LoadingState, ErrorState } from '../components/States';
import {
  Layers,
  Cpu,
  Clock,
  ArrowUpRight,
  Info,
  Calendar,
  AlertTriangle,
  Copy,
  Check
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  CartesianGrid
} from 'recharts';

// Curated representative forecast origins across the 9-day held-out test split
const SAMPLE_ORIGINS = [
  { id: '2022-06-22T05:00:00Z', label: 'Jun 22, 12:00 AM CDT — Night Baseline' },
  { id: '2022-06-22T13:00:00Z', label: 'Jun 22, 08:00 AM CDT — Commute Peak' },
  { id: '2022-06-22T15:00:00Z', label: 'Jun 22, 10:00 AM CDT — Midday Shortage' },
  { id: '2022-06-22T22:00:00Z', label: 'Jun 22, 05:00 PM CDT — Evening Rush' },
  { id: '2022-06-23T17:00:00Z', label: 'Jun 23, 12:00 PM CDT — Midday Shortage' },
  { id: '2022-06-25T04:00:00Z', label: 'Jun 24, 11:00 PM CDT — Night Entertainment' },
  { id: '2022-06-30T15:00:00Z', label: 'Jun 30, 10:00 AM CDT — High Shortage' },
];

export default function OverviewView({ onNavigateToZones, onNavigateToSurge, onNavigateToMap }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [surgeAlerts, setSurgeAlerts] = useState([]);
  const [selectedOrigin, setSelectedOrigin] = useState(SAMPLE_ORIGINS[0].id);
  const [zoneRecords, setZoneRecords] = useState([]);
  const [chartSortBy, setChartSortBy] = useState('shortage'); // 'shortage' | 'demand' | 'capacity'
  const [copiedCell, setCopiedCell] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [surgeRes, pressureRes] = await Promise.all([
        fetchSurgeAlerts({ limit: 8 }),
        fetchPressure({
          start: selectedOrigin,
          end: selectedOrigin,
          limit: 150 // Covers all 135 operational zones for this single origin
        })
      ]);

      setSurgeAlerts(surgeRes.data || []);
      setZoneRecords(pressureRes.data || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedOrigin]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  function handleCopy(text) {
    navigator.clipboard.writeText(text);
    setCopiedCell(text);
    setTimeout(() => setCopiedCell(null), 2000);
  }

  if (loading) return <LoadingState message="Loading origin snapshot and telemetry..." />;
  if (error) return <ErrorState message={error} onRetry={loadData} />;

  // Calculate system-wide aggregates for this exact 15-minute origin snapshot
  const totalZones = zoneRecords.length;
  const sysDemand = zoneRecords.reduce((acc, r) => acc + (r.predicted_rides_D || 0), 0);
  const sysCapacity = zoneRecords.reduce((acc, r) => acc + (r.estimated_capacity_C || 0), 0);
  const sysVehicles = zoneRecords.reduce((acc, r) => acc + (r.available_vehicles_V || 0), 0);
  const sysShortage = zoneRecords.reduce((acc, r) => acc + (r.estimated_unserved_demand_rides || 0), 0);

  // Pressure breakdown for this snapshot
  const pressureCounts = {
    LOW: zoneRecords.filter(r => r.pressure_level === 'LOW').length,
    NO_CAPACITY: zoneRecords.filter(r => r.pressure_level === 'NO_CAPACITY').length,
    MODERATE: zoneRecords.filter(r => r.pressure_level === 'MODERATE').length,
    HIGH: zoneRecords.filter(r => r.pressure_level === 'HIGH').length,
    CRITICAL: zoneRecords.filter(r => r.pressure_level === 'CRITICAL').length,
  };

  // Top Shortage Zones (where demand > capacity or unserved demand > 0)
  const topShortageZones = [...zoneRecords]
    .sort((a, b) => (b.estimated_unserved_demand_rides || 0) - (a.estimated_unserved_demand_rides || 0))
    .slice(0, 10);

  // Prepare chart dataset (Top 12 zones by chosen sort criterion)
  const chartData = [...zoneRecords]
    .sort((a, b) => {
      if (chartSortBy === 'demand') {
        return (b.predicted_rides_D || 0) - (a.predicted_rides_D || 0);
      }
      if (chartSortBy === 'capacity') {
        return (b.estimated_capacity_C || 0) - (a.estimated_capacity_C || 0);
      }
      // default: shortage
      return (b.estimated_unserved_demand_rides || 0) - (a.estimated_unserved_demand_rides || 0);
    })
    .slice(0, 12)
    .map(r => {
      const details = getZoneDetails(r.h3_cell);
      return {
        zoneLabel: getZoneLabel(r.h3_cell),
        rawCell: r.h3_cell,
        coordinates: details?.coordinates || 'N/A',
        demand: Number((r.predicted_rides_D || 0).toFixed(2)),
        capacity: Number((r.estimated_capacity_C || 0).toFixed(1)),
        shortage: Number((r.estimated_unserved_demand_rides || 0).toFixed(2)),
        vehicles: r.available_vehicles_V || 0,
        pressureLevel: r.pressure_level
      };
    });

  const activeOriginRecord = zoneRecords[0];
  const horizonStartLocal = activeOriginRecord ? formatChicagoTime(activeOriginRecord.target_start) : '—';
  const horizonEndLocal = activeOriginRecord ? formatChicagoTime(activeOriginRecord.target_end) : '—';

  return (
    <div className="space-y-8">
      {/* Forecast Origin Snapshot Selector & Scope Banner */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-cyan-950 text-cyan-300 border border-cyan-800/60">
                Synchronized 15-Min Snapshot
              </span>
              <span className="text-xs text-slate-400 font-mono">
                Scope: All {totalZones} Operational H3 Zones
              </span>
            </div>
            <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
              <Calendar size={18} className="text-cyan-400" />
              Evaluation Prediction Origin &amp; Horizon
            </h2>
          </div>

          {/* Origin Dropdown */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Snapshot Origin (CDT):
            </span>
            <select
              value={selectedOrigin}
              onChange={(e) => setSelectedOrigin(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 font-medium focus:border-cyan-500 focus:outline-none cursor-pointer max-w-full sm:max-w-md"
            >
              {SAMPLE_ORIGINS.map(o => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Origin Horizon Metadata Strip */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-3 border-t border-slate-800/80 text-xs text-slate-300">
          <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800">
            <span className="text-slate-400 block text-[11px]">Prediction Origin T (Local)</span>
            <span className="font-semibold text-slate-100">{formatChicagoTime(selectedOrigin)}</span>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800">
            <span className="text-slate-400 block text-[11px]">30-Min Forecast Horizon</span>
            <span className="font-semibold text-cyan-300">{horizonStartLocal.split(',')[2]?.trim() || 'Start'} &ndash; {horizonEndLocal.split(',')[2]?.trim() || 'End'}</span>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800">
            <span className="text-slate-400 block text-[11px]">Storage Timezone (UTC)</span>
            <span className="font-mono text-indigo-300 text-[11px]">{selectedOrigin}</span>
          </div>
          <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800">
            <span className="text-slate-400 block text-[11px]">Aggregation Integrity</span>
            <span className="text-emerald-400 font-medium">135 Zones &bull; No Double-Counting</span>
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="System-Wide Predicted Demand"
          value={sysDemand.toFixed(1)}
          unit="Rides / 30m"
          subtitle={`Sum of D across all ${totalZones} operational zones`}
          sourceType="PREDICTED"
          icon={Layers}
        />
        <StatCard
          title="System-Wide Fleet Capacity"
          value={sysCapacity.toFixed(1)}
          unit="Rides / 30m"
          subtitle={`${sysVehicles.toLocaleString()} vehicles (C = V \u00D7 2.0)`}
          sourceType="SIMULATED_ESTIMATE"
          icon={Cpu}
        />
        <StatCard
          title="Total Expected Shortage"
          value={sysShortage.toFixed(1)}
          unit="Unserved Rides"
          subtitle="Sum of max(0, D - C) capacity deficits"
          sourceType="SIMULATED_ESTIMATE"
          icon={AlertTriangle}
        />
        <StatCard
          title="Forecast-Eligible Universe"
          value={totalZones}
          unit="H3 Zones"
          subtitle="Causal pre-test qualified (>= 10 trips)"
          sourceType="HISTORICAL"
          icon={Clock}
        />
      </div>

      {/* Simulated Capacity & Localized Shortages Explanatory Note */}
      <div className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 flex items-start gap-3 text-xs text-slate-300">
        <Info size={16} className="text-cyan-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <span className="font-semibold text-slate-100 block">
            Simulated Fleet Capacity &amp; Localized Deficit Dynamics:
          </span>
          <p className="text-slate-400 leading-relaxed">
            Fleet capacity (<span className="font-mono text-cyan-300">C = V &times; 2.0</span>) represents a simulated fleet scenario estimate. System-wide aggregate capacity may mathematically exceed total predicted demand; however, operational pressure and unserved demand are evaluated strictly locally by individual H3 zone. A macro system-wide surplus does not imply that every local zone is adequately served, as idle vehicles in distant staging hubs cannot immediately satisfy localized demand spikes without repositioning dispatch.
          </p>
        </div>
      </div>

      {/* Primary Chart: Zone-by-Zone Demand vs. Capacity Comparison */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-indigo-950 text-indigo-300 border border-indigo-800/60">
                Operational Shortage Analysis
              </span>
              <span className="text-xs text-slate-400">
                Units: Expected Rides per 30-Minute Horizon
              </span>
            </div>
            <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider">
              Predicted Demand vs. Estimated Capacity by Zone
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Identifies zones where predicted ride demand exceeds estimated fleet capacity (Shortage $D &gt; C$)
            </p>
          </div>

          {/* Sort Control */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-400">Sort Top 12 By:</span>
            <div className="flex rounded-lg bg-slate-950 p-1 border border-slate-800 text-xs">
              <button
                onClick={() => setChartSortBy('shortage')}
                className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                  chartSortBy === 'shortage'
                    ? 'bg-rose-950 text-rose-300 font-semibold border border-rose-800/60'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Shortage (D &minus; C)
              </button>
              <button
                onClick={() => setChartSortBy('demand')}
                className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                  chartSortBy === 'demand'
                    ? 'bg-cyan-950 text-cyan-300 font-semibold border border-cyan-800/60'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Demand (D)
              </button>
              <button
                onClick={() => setChartSortBy('capacity')}
                className={`px-2.5 py-1 rounded-md transition cursor-pointer ${
                  chartSortBy === 'capacity'
                    ? 'bg-indigo-950 text-indigo-300 font-semibold border border-indigo-800/60'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Capacity (C)
              </button>
            </div>
          </div>
        </div>

        {/* Recharts Grouped Bar Chart */}
        <div className="h-72 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 15, right: 15, left: -10, bottom: 25 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="zoneLabel"
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                interval={0}
                angle={-25}
                textAnchor="end"
              />
              <YAxis
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                label={{ value: 'Rides / 30m', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const data = payload[0].payload;
                    return (
                      <div className="bg-slate-950 border border-slate-700 p-3 rounded-lg shadow-xl text-xs space-y-1.5 font-sans">
                        <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-1.5 font-bold text-slate-100">
                          <span>{data.zoneLabel}</span>
                          <span className="font-mono text-[10px] text-cyan-400">{data.rawCell}</span>
                        </div>
                        <div className="text-[11px] text-slate-400">Centroid: {data.coordinates}</div>
                        <div className="flex justify-between gap-4 text-cyan-400 font-semibold">
                          <span>Predicted Demand (D):</span>
                          <span>{data.demand} rides</span>
                        </div>
                        <div className="flex justify-between gap-4 text-indigo-400 font-semibold">
                          <span>Estimated Capacity (C):</span>
                          <span>{data.capacity} rides ({data.vehicles} veh)</span>
                        </div>
                        <div className="flex justify-between gap-4 text-rose-400 font-bold border-t border-slate-800/80 pt-1">
                          <span>Expected Shortage (D &minus; C):</span>
                          <span>{data.shortage} rides</span>
                        </div>
                        <div className="flex justify-between gap-4 text-slate-300">
                          <span>Pressure Level:</span>
                          <span className="font-semibold">{data.pressureLevel}</span>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ fontSize: '11px', paddingBottom: '10px' }}
              />
              <Bar
                dataKey="demand"
                fill="#06b6d4"
                radius={[4, 4, 0, 0]}
                name="Predicted Demand (D)"
              />
              <Bar
                dataKey="capacity"
                fill="#6366f1"
                radius={[4, 4, 0, 0]}
                name="Estimated Capacity (C = V \u00D7 2.0)"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-3 gap-2">
          <span>
            <strong className="text-slate-300">Operational Decision Rule:</strong> Shortage occurs when Demand (D) exceeds Capacity (C). Zones with C = 0 and D &gt; 0 indicate NO_CAPACITY.
          </span>
          <span className="font-mono text-cyan-400 shrink-0">
            Units: Rides / 30m (Compatible)
          </span>
        </div>
      </div>

      {/* Two-Column Grid: Top Shortage Zones & Pressure Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Top Shortage Zones Table */}
        <div className="lg:col-span-2 bg-slate-900/90 border border-slate-800 rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-rose-950 text-rose-300 border border-rose-800/60">
                  Priority Deficits
                </span>
                <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider">
                  Top Expected Shortage Zones
                </h3>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Zones ranked by expected unserved demand: $\max(0, D - C)$ rides
              </p>
            </div>
            <div className="flex items-center gap-3">
              {onNavigateToMap && (
                <button
                  onClick={onNavigateToMap}
                  className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-medium cursor-pointer"
                >
                  Map Heatmap <ArrowUpRight size={14} />
                </button>
              )}
              <button
                onClick={onNavigateToZones}
                className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 font-medium cursor-pointer"
              >
                All Zones <ArrowUpRight size={14} />
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="pb-2 font-semibold">Zone Label</th>
                  <th className="pb-2 font-semibold">H3 Hex Identifier</th>
                  <th className="pb-2 font-semibold text-right">Demand (D)</th>
                  <th className="pb-2 font-semibold text-right">Capacity (C)</th>
                  <th className="pb-2 font-semibold text-right text-rose-400">Shortage (D&minus;C)</th>
                  <th className="pb-2 font-semibold text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans">
                {topShortageZones.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-4 text-center text-slate-400">
                      No shortage observations in this snapshot
                    </td>
                  </tr>
                ) : (
                  topShortageZones.map((row, idx) => {
                    const label = getZoneLabel(row.h3_cell);
                    return (
                      <tr key={idx} className="hover:bg-slate-800/30 transition">
                        <td className="py-2.5 font-bold text-slate-100">{label}</td>
                        <td className="py-2.5 font-mono text-slate-400">
                          <div className="flex items-center gap-1.5">
                            <span>{row.h3_cell.slice(0, 10)}...</span>
                            <button
                              onClick={() => handleCopy(row.h3_cell)}
                              title="Copy full H3 cell identifier"
                              className="text-slate-500 hover:text-cyan-400 transition cursor-pointer p-0.5"
                            >
                              {copiedCell === row.h3_cell ? (
                                <Check size={11} className="text-emerald-400" />
                              ) : (
                                <Copy size={11} />
                              )}
                            </button>
                          </div>
                        </td>
                        <td className="py-2.5 text-right font-medium text-cyan-400">
                          {row.predicted_rides_D?.toFixed(2)}
                        </td>
                        <td className="py-2.5 text-right font-medium text-indigo-400">
                          {row.estimated_capacity_C?.toFixed(1)}
                        </td>
                        <td className="py-2.5 text-right font-bold text-rose-400">
                          {(row.estimated_unserved_demand_rides || 0).toFixed(2)}
                        </td>
                        <td className="py-2.5 text-center">
                          <Badge value={row.pressure_level} />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Snapshot Pressure Level Distribution Card */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider mb-1">
              Snapshot Pressure Distribution
            </h3>
            <p className="text-xs text-slate-400 mb-5">
              Contract Table 6 status across {totalZones} operational zones at this origin
            </p>

            <div className="space-y-3.5">
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-emerald-400 font-medium">Normal / Low Pressure</span>
                  <span className="text-slate-300">
                    {pressureCounts.LOW} ({((pressureCounts.LOW / totalZones) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-emerald-500 h-full rounded-full transition-all duration-500"
                    style={{ width: `${(pressureCounts.LOW / totalZones) * 100}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400 font-medium">No Capacity (C=0, D&gt;0)</span>
                  <span className="text-slate-300">
                    {pressureCounts.NO_CAPACITY} ({((pressureCounts.NO_CAPACITY / totalZones) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-slate-500 h-full rounded-full transition-all duration-500"
                    style={{ width: `${(pressureCounts.NO_CAPACITY / totalZones) * 100}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-yellow-400 font-medium">Moderate / Elevated</span>
                  <span className="text-slate-300">
                    {pressureCounts.MODERATE} ({((pressureCounts.MODERATE / totalZones) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-yellow-500 h-full rounded-full transition-all duration-500"
                    style={{ width: `${(pressureCounts.MODERATE / totalZones) * 100}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-rose-400 font-medium">High &amp; Critical Pressure</span>
                  <span className="text-slate-300">
                    {pressureCounts.HIGH + pressureCounts.CRITICAL} ({(((pressureCounts.HIGH + pressureCounts.CRITICAL) / totalZones) * 100).toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-rose-500 h-full rounded-full transition-all duration-500"
                    style={{ width: `${((pressureCounts.HIGH + pressureCounts.CRITICAL) / totalZones) * 100}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Plain-English NO_CAPACITY Explanation */}
          <div className="mt-6 p-3 rounded-lg bg-slate-950/70 border border-slate-800/80 text-[11px] text-slate-300 space-y-1.5 leading-relaxed">
            <div className="flex items-center gap-1.5 text-cyan-300 font-semibold">
              <Info size={13} />
              Understanding NO_CAPACITY
            </div>
            <p className="text-slate-400">
              NO_CAPACITY indicates that the multinomial fleet simulation allocated 0 available vehicles ($V=0$) to a peripheral zone during this 30-minute window while the ML model predicted positive fractional micro-demand ($D &lt; 1.0$).
            </p>
            <p className="text-slate-400">
              This is a simulated decision-support estimate, <strong>not</strong> real-world driver GPS absence. Nearby zones may possess available capacity.
            </p>
          </div>
        </div>
      </div>

      {/* Recent Surge Alerts Callout Banner */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-950 text-amber-300 border border-amber-800/60">
                Heuristic Alerts
              </span>
              <h3 className="text-sm font-bold text-slate-100 uppercase tracking-wider">
                Recent Surge Alerts Feed
              </h3>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Historical simulated alerts flagged when predicted demand exceeds capacity thresholds ($D \ge 5.0, P \ge 1.2$)
            </p>
          </div>
          <button
            onClick={onNavigateToSurge}
            className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 font-medium cursor-pointer"
          >
            All 8 Alerts <ArrowUpRight size={14} />
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {surgeAlerts.slice(0, 4).map((alert) => {
            const label = getZoneLabel(alert.h3_cell);
            return (
              <div
                key={alert.alert_id}
                className="p-3.5 rounded-lg bg-slate-950/60 border border-slate-800 flex flex-col justify-between hover:border-slate-700 transition"
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-xs text-slate-100">{label}</span>
                    <Badge value={alert.severity} />
                  </div>
                  <div className="font-mono text-[10px] text-slate-400 truncate mb-2">
                    {alert.h3_cell}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Origin: {formatChicagoTime(alert.forecast_origin)}
                  </div>
                </div>

                <div className="mt-3 pt-2 border-t border-slate-800 flex items-center justify-between">
                  <span className="text-[11px] text-slate-400">Predicted Demand:</span>
                  <span className="text-xs font-bold text-rose-400">
                    {alert.predicted_demand?.toFixed(1)} rides
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
