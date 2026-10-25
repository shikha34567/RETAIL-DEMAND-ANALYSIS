import React, { useState, useEffect, useCallback } from 'react';
import { fetchSurgeAlerts, formatChicagoTime } from '../services/api';
import { getZoneLabel } from '../services/zoneLabels';
import Badge from '../components/Badge';
import { LoadingState, ErrorState, EmptyState } from '../components/States';
import {
  ShieldAlert,
  Flame,
  Info,
  Copy,
  Check,
  Filter
} from 'lucide-react';

export default function SurgeAlertsView() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [totalAlerts, setTotalAlerts] = useState(0);
  const [severityFilter, setSeverityFilter] = useState('');
  const [copiedId, setCopiedId] = useState(null);

  const loadSurgeAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchSurgeAlerts({
        severity: severityFilter || undefined,
        limit: 50
      });
      setAlerts(res.data || []);
      setTotalAlerts(res.total_records || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [severityFilter]);

  useEffect(() => {
    loadSurgeAlerts();
  }, [loadSurgeAlerts]);

  function handleCopy(text, id) {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <div className="space-y-6">
      {/* Simulation Disclaimer Banner */}
      <div className="p-5 rounded-xl bg-amber-950/30 border border-amber-800/50 flex items-start gap-4 text-xs text-amber-200">
        <div className="p-2 rounded-lg bg-amber-900/50 text-amber-300 shrink-0">
          <ShieldAlert size={20} />
        </div>
        <div className="space-y-1">
          <h3 className="font-semibold text-amber-100 text-sm">
            Simulated Supply Intelligence Feed
          </h3>
          <p className="text-amber-300/80 leading-relaxed">
            Surge alerts are heuristic decision-support flags evaluated against simulated driver supply scenarios (<span className="font-mono">C = V &times; r</span>).
            Unlike Zone Intelligence (which tracks baseline operational pressure <span className="font-mono">P = D / C</span> across all 135 zones), the Surge Alerts feed applies multi-factor eligibility criteria: it requires a minimum demand threshold (<span className="font-mono">D &ge; 5.0</span> rides) to filter micro-demand noise, a pressure ratio <span className="font-mono">P &ge; 1.20</span>, and verified baseline demand growth (<span className="font-mono">D / baseline &ge; 1.30</span>). Peripheral zones classified as Critical or No Capacity in Zone Intelligence do not trigger alerts unless they satisfy these criteria. These flags do not represent live dynamic pricing or measured GPS fleet telemetry.
          </p>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="p-4 rounded-xl bg-slate-900/90 border border-slate-800 shadow-sm flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Filter size={15} className="text-slate-400" />
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Severity Filter:
          </span>
          <div className="flex items-center gap-1.5">
            {['', 'CRITICAL', 'HIGH'].map((sev) => (
              <button
                key={sev}
                onClick={() => setSeverityFilter(sev)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer border ${
                  severityFilter === sev
                    ? 'bg-cyan-950 border-cyan-800 text-cyan-200'
                    : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }`}
              >
                {sev === '' ? 'All Severities' : sev}
              </button>
            ))}
          </div>
        </div>

        <div className="text-xs text-slate-400">
          Showing <span className="font-semibold text-slate-200">{alerts.length}</span> of{' '}
          <span className="font-semibold text-slate-200">{totalAlerts}</span> persisted alerts
        </div>
      </div>

      {/* Surge Alert Cards Grid */}
      {loading ? (
        <LoadingState message="Fetching persisted surge alerts..." />
      ) : error ? (
        <ErrorState message={error} onRetry={loadSurgeAlerts} />
      ) : alerts.length === 0 ? (
        <EmptyState message="No surge alerts found for the selected severity." />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {alerts.map((alert) => (
            <div
              key={alert.alert_id}
              className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700 transition flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <Badge value={alert.severity} />
                  <span className="text-[10px] text-slate-400 font-mono">
                    {alert.alert_id.slice(0, 14)}
                  </span>
                </div>

                <div className="mb-4">
                  <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                    <span>Target Zone:</span>
                    <span className="font-bold text-slate-100">{getZoneLabel(alert.h3_cell)}</span>
                  </div>
                  <div className="flex items-center justify-between bg-slate-950 p-2 rounded-lg border border-slate-800 font-mono text-xs text-slate-200">
                    <span>{alert.h3_cell}</span>
                    <button
                      onClick={() => handleCopy(alert.h3_cell, alert.alert_id)}
                      className="text-slate-400 hover:text-cyan-400 transition cursor-pointer"
                      title="Copy H3 cell"
                    >
                      {copiedId === alert.alert_id ? (
                        <Check size={13} className="text-emerald-400" />
                      ) : (
                        <Copy size={13} />
                      )}
                    </button>
                  </div>
                </div>

                <div className="space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Forecast Origin:</span>
                    <span className="text-slate-300 font-medium">
                      {formatChicagoTime(alert.forecast_origin)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Predicted Demand (30m):</span>
                    <span className="text-cyan-400 font-bold">
                      {alert.predicted_demand?.toFixed(2)} rides
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Observed Demand:</span>
                    <span className="text-slate-300 font-medium">
                      {alert.observed_demand} rides
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <Flame size={12} className="text-rose-400" />
                  <span>Surge Triggered</span>
                </span>
                <span className="font-mono text-[10px] text-slate-400">
                  {alert.simulation_run_id}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Surge Criteria Specification Card */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 shadow-sm text-xs text-slate-400 leading-relaxed">
        <h4 className="font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <Info size={14} className="text-cyan-400" />
          Heuristic Surge Detection Criteria (Phase 4 Specification)
        </h4>
        <ul className="list-disc list-inside space-y-1">
          <li><strong>Minimum Demand Threshold:</strong> Predicted demand $D \ge 5.0$ rides in the 30-minute window (filters micro-demand volatility in peripheral zones).</li>
          <li><strong>Pressure Ratio Trigger:</strong> Demand / Capacity ratio $P \ge 1.20$ (evaluating simulated available driver capacity $C = V \times r$).</li>
          <li><strong>Severity Hierarchy:</strong> Labeled <span className="text-rose-400 font-semibold">CRITICAL</span> when $P \ge 1.50$ or $D \ge 25.0$; labeled <span className="text-amber-400 font-semibold">HIGH</span> otherwise.</li>
        </ul>
      </div>
    </div>
  );
}
