import React from 'react';
import {
  Navigation,
  CheckCircle2,
  AlertTriangle,
  Info,
  X,
  TrendingDown,
  TrendingUp,
  Car
} from 'lucide-react';

const SEVERITY_STYLES = {
  info: {
    border: 'border-cyan-500/60',
    bg: 'bg-slate-950/95',
    titleColor: 'text-cyan-300',
    iconColor: 'text-cyan-400',
    icon: Navigation
  },
  success: {
    border: 'border-emerald-500/60',
    bg: 'bg-slate-950/95',
    titleColor: 'text-emerald-300',
    iconColor: 'text-emerald-400',
    icon: TrendingDown
  },
  warning: {
    border: 'border-amber-500/60',
    bg: 'bg-slate-950/95',
    titleColor: 'text-amber-300',
    iconColor: 'text-amber-400',
    icon: TrendingUp
  },
  neutral: {
    border: 'border-slate-700/80',
    bg: 'bg-slate-950/95',
    titleColor: 'text-slate-300',
    iconColor: 'text-slate-400',
    icon: Info
  }
};

/**
 * Toast notification container positioned in the bottom-right of the Command Centre map.
 * Displays up to 4 simultaneous notifications with auto-dismiss and manual close.
 */
export default function SimulationToastContainer({ toasts, onDismiss, hasInspectorOpen = false }) {
  if (!toasts || toasts.length === 0) return null;

  // Show no more than 4 visible notifications simultaneously
  const visibleToasts = toasts.slice(-4);

  const positionClass = hasInspectorOpen
    ? 'bottom-4 right-4 sm:right-92 z-[1050]'
    : 'bottom-4 right-4 z-[1050]';

  return (
    <aside
      aria-label="Simulation notifications"
      className={`absolute ${positionClass} flex flex-col gap-2 w-84 max-w-[calc(100vw-32px)] pointer-events-none transition-all duration-200`}
    >
      {visibleToasts.map((t) => {
        const style = SEVERITY_STYLES[t.severity] || SEVERITY_STYLES.neutral;
        const IconComponent = style.icon;

        return (
          <div
            key={t.id}
            className={`pointer-events-auto p-3 rounded-xl border ${style.border} ${style.bg} shadow-2xl backdrop-blur-md transition-all duration-200 animate-in fade-in slide-in-from-bottom-2 space-y-1.5`}
          >
            {/* Header: Icon, Title & Close Button */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <IconComponent size={14} className={`${style.iconColor} shrink-0`} />
                <span className={`text-xs font-bold uppercase tracking-wider truncate ${style.titleColor}`}>
                  {t.title}
                </span>
              </div>
              <button
                onClick={() => onDismiss(t.id)}
                title="Dismiss notification"
                className="text-slate-500 hover:text-slate-200 p-0.5 rounded transition cursor-pointer"
              >
                <X size={13} />
              </button>
            </div>

            {/* Message Body */}
            <p className="text-xs text-slate-200 font-medium leading-snug">
              {t.message}
            </p>

            {/* Detail / Disclaimer Footer */}
            {t.detail && (
              <p className="text-[10px] text-slate-400 leading-tight">
                {t.detail}
              </p>
            )}
          </div>
        );
      })}
    </aside>
  );
}
