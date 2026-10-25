import React from 'react';

export function LoadingState({ message = 'Loading artifact data...' }) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center rounded-xl bg-slate-900/40 border border-slate-800">
      <div className="w-8 h-8 border-3 border-cyan-500 border-t-transparent rounded-full animate-spin mb-4" />
      <p className="text-sm text-slate-400 font-medium">{message}</p>
      <span className="text-xs text-slate-400 mt-1">Reading Parquet / JSON evidence stores</span>
    </div>
  );
}

export function ErrorState({ title = 'Failed to Load Data', message, onRetry }) {
  return (
    <div className="p-6 rounded-xl bg-rose-950/30 border border-rose-800/50 text-slate-200">
      <div className="flex items-start gap-4">
        <div className="p-2 rounded-lg bg-rose-900/50 text-rose-300">
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-rose-200">{title}</h3>
          <p className="text-sm text-rose-300/80 mt-1 leading-relaxed">{message}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-4 px-3 py-1.5 text-xs font-medium rounded-lg bg-rose-800/60 hover:bg-rose-700/80 text-rose-100 transition border border-rose-700 cursor-pointer"
            >
              Retry Request
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function EmptyState({ title = 'No Records Found', message = 'No data matching your current filter criteria.' }) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center rounded-xl bg-slate-900/40 border border-slate-800">
      <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center text-slate-400 mb-3">
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      </div>
      <h4 className="text-sm font-medium text-slate-300">{title}</h4>
      <p className="text-xs text-slate-400 mt-1 max-w-sm">{message}</p>
    </div>
  );
}

