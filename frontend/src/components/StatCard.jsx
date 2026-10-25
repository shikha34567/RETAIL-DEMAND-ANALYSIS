import React from 'react';
import Badge from './Badge';

export default function StatCard({
  title,
  value,
  unit = '',
  subtitle,
  sourceType,
  icon: Icon,
  trend,
  className = ''
}) {
  return (
    <div className={`bg-slate-900/90 border border-slate-800 rounded-xl p-5 shadow-sm backdrop-blur hover:border-slate-700 transition ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {title}
        </span>
        <div className="flex items-center gap-2">
          {sourceType && <Badge type="source" value={sourceType} />}
          {Icon && (
            <div className="p-2 rounded-lg bg-slate-800/80 text-cyan-400">
              <Icon size={18} />
            </div>
          )}
        </div>
      </div>

      <div className="flex items-baseline gap-2">
        <div className="text-2xl lg:text-3xl font-bold tracking-tight text-slate-100">
          {value !== null && value !== undefined ? value : '—'}
        </div>
        {unit && <span className="text-sm font-medium text-slate-400">{unit}</span>}
      </div>

      {subtitle && (
        <p className="mt-2 text-xs text-slate-400 leading-relaxed">
          {subtitle}
        </p>
      )}

      {trend && (
        <div className="mt-2 text-xs font-medium text-cyan-400">
          {trend}
        </div>
      )}
    </div>
  );
}

