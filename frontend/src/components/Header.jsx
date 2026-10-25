import React from 'react';
import { Clock, ShieldCheck, AlertCircle, Database } from 'lucide-react';

export default function Header({ title, health, metadata }) {
  const isHealthy = health?.status === 'HEALTHY';

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0 z-20 flex items-center justify-between px-8">
      <div>
        <h2 className="text-lg font-bold text-slate-100 tracking-tight">{title}</h2>
      </div>

      <div className="flex items-center gap-3">
        {/* Timezone Pill */}
        <div className="hidden md:flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300">
          <Clock size={13} className="text-cyan-400" />
          <span>America/Chicago (Local)</span>
          <span className="text-[10px] text-slate-400 font-mono">UTC Storage</span>
        </div>

        {/* Dataset Pill */}
        <div className="hidden lg:flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300">
          <Database size={13} className="text-indigo-400" />
          <span>{metadata?.dataset_window || 'June 2022'}</span>
          <span className="text-[10px] text-slate-400 font-mono">H3 Res-8</span>
        </div>

        {/* Backend Health Status */}
        <div className={`flex items-center gap-1.5 px-3 py-1 rounded-lg border text-xs font-medium transition ${
          isHealthy
            ? 'bg-emerald-950/50 border-emerald-800/60 text-emerald-300'
            : 'bg-rose-950/50 border-rose-800/60 text-rose-300'
        }`}>
          {isHealthy ? (
            <ShieldCheck size={14} className="text-emerald-400" />
          ) : (
            <AlertCircle size={14} className="text-rose-400" />
          )}
          <span>{isHealthy ? 'FastAPI Connected' : 'API Unavailable'}</span>
        </div>
      </div>
    </header>
  );
}
