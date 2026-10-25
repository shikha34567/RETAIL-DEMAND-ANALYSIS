import React from 'react';

/**
 * Standardized badge for pressure levels, alert severities, and source types.
 */
export default function Badge({ type, value, children }) {
  const label = children || value;
  if (!label) return null;

  let bg = 'bg-slate-800 text-slate-300 border-slate-700';

  // Pressure Levels
  if (value === 'CRITICAL' || type === 'critical') {
    bg = 'bg-rose-950/70 text-rose-300 border-rose-800/60';
  } else if (value === 'HIGH' || type === 'high') {
    bg = 'bg-amber-950/70 text-amber-300 border-amber-800/60';
  } else if (value === 'MODERATE' || value === 'ELEVATED' || type === 'moderate') {
    bg = 'bg-yellow-950/60 text-yellow-300 border-yellow-800/50';
  } else if (value === 'LOW' || value === 'NORMAL' || type === 'low') {
    bg = 'bg-emerald-950/60 text-emerald-300 border-emerald-800/50';
  } else if (value === 'NO_CAPACITY' || value === 'NO_ESTIMATED_CAPACITY' || type === 'no_capacity') {
    bg = 'bg-slate-800 text-slate-400 border-slate-700';
  }

  // Source Types
  if (type === 'source') {
    if (value === 'PREDICTED') {
      bg = 'bg-cyan-950/60 text-cyan-300 border-cyan-800/50';
    } else if (value === 'SIMULATED' || value === 'SIMULATED_ESTIMATE') {
      bg = 'bg-indigo-950/60 text-indigo-300 border-indigo-800/50';
    } else if (value === 'HISTORICAL' || value === 'OBSERVED') {
      bg = 'bg-teal-950/60 text-teal-300 border-teal-800/50';
    } else if (value === 'ESTIMATED') {
      bg = 'bg-purple-950/60 text-purple-300 border-purple-800/50';
    }
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${bg}`}>
      {label}
    </span>
  );
}

