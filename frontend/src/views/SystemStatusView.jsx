import React, { useState, useEffect } from 'react';
import { fetchHealth, fetchMetadata, fetchMetrics, formatChicagoTime } from '../services/api';
import { getZoneLabel } from '../services/zoneLabels';
import Badge from '../components/Badge';
import { LoadingState, ErrorState } from '../components/States';
import {
  Server,
  Layers,
  ShieldCheck,
  Cpu,
  Clock,
  Compass,
  AlertOctagon
} from 'lucide-react';

export default function SystemStatusView() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [healthData, setHealthData] = useState(null);
  const [metadata, setMetadata] = useState(null);
  const [metricsData, setMetricsData] = useState(null);

  useEffect(() => {
    loadSystemInfo();
  }, []);

  async function loadSystemInfo() {
    setLoading(true);
    setError(null);
    try {
      const [healthRes, metaRes, metricsRes] = await Promise.all([
        fetchHealth(),
        fetchMetadata(),
        fetchMetrics().catch(() => null)
      ]);
      setHealthData(healthRes);
      setMetadata(metaRes);
      setMetricsData(metricsRes);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (loading) return <LoadingState message="Loading system status and governance metadata..." />;
  if (error) return <ErrorState message={error} onRetry={loadSystemInfo} />;

  const leakedZones = [
    { id: '882664528bfffff', desc: 'Leaked cell 1: Trip 10 occurred after June 22 05:00 UTC' },
    { id: '882664cf4bfffff', desc: 'Leaked cell 2: Trip 10 occurred after June 22 05:00 UTC' },
    { id: '882664d89dfffff', desc: 'Leaked cell 3: Trip 10 occurred after June 22 05:00 UTC' },
    { id: '882664d8d5fffff', desc: 'Leaked cell 4: Trip 10 occurred after June 22 05:00 UTC' },
  ];

  return (
    <div className="space-y-6">
      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 flex items-center justify-between">
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">FastAPI Backend</span>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-lg font-bold text-slate-100">{healthData?.status || 'HEALTHY'}</span>
            </div>
            <p className="text-xs text-slate-400">Environment: {healthData?.environment || 'development'}</p>
            <p className="text-[11px] text-slate-400 font-mono">
              Reported: {formatChicagoTime(healthData?.timestamp)}
            </p>
          </div>
          <div className="p-3 rounded-lg bg-emerald-950/40 text-emerald-400 border border-emerald-800/40">
            <Server size={24} />
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 flex items-center justify-between">
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Model Champion</span>
            <div className="text-lg font-bold text-cyan-300">
              {metadata?.champion_model || 'XGBoost Regressor'}
            </div>
            <p className="text-xs text-slate-400">
              {metricsData?.overall_metrics?.xgboost ? (
                `WAPE: ${((metricsData.overall_metrics.xgboost.wape || 0) * 100).toFixed(2)}% | MAE: ${metricsData.overall_metrics.xgboost.mae?.toFixed(4)}`
              ) : (
                '116,505 held-out test rows'
              )}
            </p>
          </div>
          <div className="p-3 rounded-lg bg-cyan-950/40 text-cyan-400 border border-cyan-800/40">
            <Cpu size={24} />
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 flex items-center justify-between">
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Target Timezone</span>
            <div className="text-lg font-bold text-indigo-300">America/Chicago</div>
            <p className="text-xs text-slate-400">Stored in UTC, rendered locally</p>
          </div>
          <div className="p-3 rounded-lg bg-indigo-950/40 text-indigo-400 border border-indigo-800/40">
            <Clock size={24} />
          </div>
        </div>
      </div>

      {/* 4 Distinct Zone Count Hierarchy */}
      <div className="p-6 rounded-xl bg-slate-900/70 border border-slate-800 space-y-5">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              <Layers size={18} className="text-cyan-400" />
              Spatial Hierarchy & Zone Universe Reconciliation
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Audit-verified breakdown of spatial partition counts across Phase 1, Phase 3, Phase 4, and Phase 5A
            </p>
          </div>
          <Badge type="info" text="4 DISTINCT DEFINITIONS" />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
              <span>Catalog Cells</span>
              <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">Phase 1</span>
            </div>
            <div className="text-2xl font-bold font-mono text-slate-100">
              {metadata?.total_catalog_zones ?? 239}
            </div>
            <p className="text-xs text-slate-400">
              Total observed H3 Resolution 8 cells with at least 1 trip pickup in Chicago June 2022 raw taxi data.
            </p>
          </div>

          <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400 font-semibold">
              <span>Retrospective Qualified</span>
              <span className="px-2 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800/40 text-[10px]">Full-Month</span>
            </div>
            <div className="text-2xl font-bold font-mono text-amber-300">
              {metadata?.retrospective_operational_zones ?? 139}
            </div>
            <p className="text-xs text-slate-400">
              Cells with &ge; 10 trips across the entire calendar month. Contains 4 post-split qualifying cells.
            </p>
          </div>

          <div className="p-4 rounded-lg bg-slate-950/60 border border-cyan-800/40 bg-cyan-950/10 space-y-2">
            <div className="flex items-center justify-between text-xs text-cyan-400 font-semibold">
              <span>Forecast Eligible</span>
              <span className="px-2 py-0.5 rounded bg-cyan-900/50 text-cyan-300 border border-cyan-700/50 text-[10px]">Causal Pre-Test</span>
            </div>
            <div className="text-2xl font-bold font-mono text-cyan-300">
              {metadata?.forecast_eligible_zones ?? 135}
            </div>
            <p className="text-xs text-slate-400">
              Qualified with &ge; 10 trips <em>strictly before</em> the June 22 05:00 UTC test split. Zero lookahead leakage.
            </p>
          </div>

          <div className="p-4 rounded-lg bg-slate-950/60 border border-emerald-800/40 bg-emerald-950/10 space-y-2">
            <div className="flex items-center justify-between text-xs text-emerald-400 font-semibold">
              <span>Operational Universe</span>
              <span className="px-2 py-0.5 rounded bg-emerald-900/50 text-emerald-300 border border-emerald-700/50 text-[10px]">Phase 3–5</span>
            </div>
            <div className="text-2xl font-bold font-mono text-emerald-300">
              {metadata?.operational_zone_count ?? 135}
            </div>
            <p className="text-xs text-slate-400">
              Active operational forecast & supply pressure universe evaluated across all 864 test origins.
            </p>
          </div>
        </div>

        {/* Data Governance Audit Note */}
        <div className="p-4 rounded-lg bg-sky-950/20 border border-sky-800/40 text-xs space-y-2">
          <div className="flex items-center gap-2 font-semibold text-sky-300">
            <ShieldCheck size={16} className="text-cyan-400" />
            Data Governance Audit Note: Temporal Leakage Prevention (The 4 Excluded Cells)
          </div>
          <p className="text-sky-200/80 leading-relaxed">
            During Phase 1, 139 cells met the &ge; 10 trip threshold over the full June 2022 month. However, a rigorous chronological audit in Phase 3 revealed that 4 cells reached their 10th trip only <strong>after</strong> June 22 05:00 UTC. To prevent lookahead leakage into training, those 4 cells were permanently quarantined from the operational forecast universe:
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 pt-1 text-[11px]">
            {leakedZones.map((z) => (
              <div key={z.id} className="p-2 rounded bg-slate-900 border border-sky-900/50 text-sky-300">
                <span className="font-bold text-sky-200 block">{getZoneLabel(z.id)}</span>
                <span className="truncate block font-mono text-[10px] text-sky-400/80">{z.id}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* System Governance & Parameters */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pipeline & Contract Parameters */}
        <div className="p-6 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
          <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
            <Compass size={16} className="text-cyan-400" />
            Pipeline Parameters & Contracts
          </h3>
          <div className="space-y-2 text-xs divide-y divide-slate-800/60">
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">Prediction Time Grid</span>
              <span className="font-mono text-slate-200">15-Minute Origins</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">Forecasting Horizon</span>
              <span className="font-mono text-slate-200">[T, T + 30 minutes)</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">H3 Spatial Resolution</span>
              <span className="font-mono text-slate-200">Resolution 8 (~0.737 km²)</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">Temporal Split Boundary</span>
              <span className="font-mono text-slate-200">June 22, 2022 05:00 UTC (21d / 9d)</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">Capacity Formula</span>
              <span className="font-mono text-slate-200">C = V &times; r (r = 1.2 trips/veh)</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-slate-400">High Pressure Threshold</span>
              <span className="font-mono text-slate-200">Index &gt; 1.25 or (C=0 &and; D&gt;0)</span>
            </div>
          </div>
        </div>

        {/* Academic Governance & Integrity Boundaries */}
        <div className="p-6 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
          <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
            <ShieldCheck size={16} className="text-indigo-400" />
            Academic Governance & Scope Boundaries
          </h3>
          <div className="space-y-3 text-xs text-slate-400 leading-relaxed">
            <div className="flex items-start gap-2.5">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
              <div>
                <strong className="text-slate-200">Simulated Vehicle Supply:</strong> Driver supply counts are generated using a Poisson simulation model (<code className="text-cyan-300">SIMULATED_ESTIMATE</code>). They reflect synthetic decision-support tests, not live telematics.
              </div>
            </div>
            <div className="flex items-start gap-2.5">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
              <div>
                <strong className="text-slate-200">Strict Scope Boundaries:</strong> Redis, Supabase, LSTM recurrent models, passenger booking, fleet dispatch, and payments are strictly out of scope for this academic telemetry system.
              </div>
            </div>
            <div className="flex items-start gap-2.5">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
              <div>
                <strong className="text-slate-200">Immutable Artifacts:</strong> Parquet tables and JSON evaluation logs in <code className="text-slate-300">data/</code> and <code className="text-slate-300">models/</code> are read-only and preserved across all API/UI operations.
              </div>
            </div>
            <div className="flex items-start gap-2.5">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
              <div>
                <strong className="text-slate-200">Honest Zero Representation:</strong> Missing telemetry is never silently coerced to zero without explicit zone universe alignment. Zero capacity is handled without IEEE infinity serialization.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
