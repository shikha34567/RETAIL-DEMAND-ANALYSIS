import React from 'react';
import {
  LayoutDashboard,
  MapPin,
  Map,
  TrendingUp,
  AlertTriangle,
  Server,
  Activity,
  Layers
} from 'lucide-react';

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, desc: 'Demand & Supply KPIs' },
  { id: 'map', label: 'Command Centre Map', icon: Map, desc: 'Interactive H3 Heatmap' },
  { id: 'zones', label: 'Zone Intelligence', icon: MapPin, desc: 'H3 Cells & Pressure' },
  { id: 'models', label: 'Model Performance', icon: TrendingUp, desc: 'XGBoost vs Baselines' },
  { id: 'surge', label: 'Surge Alerts', icon: AlertTriangle, desc: 'Persisted Alert Feed' },
  { id: 'system', label: 'System & Governance', icon: Server, desc: 'Metadata & Artifacts' },
];

export default function Sidebar({ activeTab, onSelectTab }) {
  return (
    <aside className="w-64 bg-slate-950 border-r border-slate-800 flex flex-col shrink-0 min-h-screen">
      {/* Brand Header */}
      <div className="p-6 border-b border-slate-800/80">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-600 flex items-center justify-center text-white shadow-lg shadow-cyan-950/50">
            <Layers size={20} className="stroke-[2.2]" />
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-100 tracking-tight">RideIntel</h1>
            <p className="text-xs text-cyan-400 font-mono font-medium">Chicago Demand & Supply</p>
          </div>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 p-4 space-y-1.5">
        <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
          Analytics Views
        </div>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              className={`w-full flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-left transition cursor-pointer group ${
                isActive
                  ? 'bg-cyan-950/50 border border-cyan-800/60 text-cyan-200 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border border-transparent'
              }`}
            >
              <Icon
                size={18}
                className={`transition ${isActive ? 'text-cyan-400' : 'text-slate-400 group-hover:text-slate-300'}`}
              />
              <div className="flex-1 truncate">
                <div className={`text-sm font-medium ${isActive ? 'text-slate-100' : 'text-slate-300'}`}>
                  {item.label}
                </div>
                <div className="text-[11px] text-slate-400 truncate">
                  {item.desc}
                </div>
              </div>
            </button>
          );
        })}
      </nav>

      {/* Academic Prototype Notice */}
      <div className="p-4 m-4 rounded-xl bg-slate-900/60 border border-slate-800/80 text-[11px] text-slate-400 leading-relaxed">
        <div className="flex items-center gap-1.5 font-semibold text-slate-300 mb-1">
          <Activity size={13} className="text-cyan-400" />
          <span>Research Prototype</span>
        </div>
        Data reflects Chicago historical trips (June 2022). Vehicle supply is simulated scenario analysis.
      </div>
    </aside>
  );
}

