import React, { useState, useEffect, lazy, Suspense, Component } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import { LoadingState, ErrorState } from './components/States';
import OverviewView from './views/OverviewView';
import { fetchHealth, fetchMetadata } from './services/api';

const ChicagoMapView = lazy(() => import('./views/ChicagoMapView'));
const ZoneIntelligenceView = lazy(() => import('./views/ZoneIntelligenceView'));
const ModelPerformanceView = lazy(() => import('./views/ModelPerformanceView'));
const SurgeAlertsView = lazy(() => import('./views/SurgeAlertsView'));
const SystemStatusView = lazy(() => import('./views/SystemStatusView'));

const TAB_TITLES = {
  overview: 'Executive Demand & Supply Overview',
  map: 'Fleet Simulation Command Centre — Chicago H3 Heatmap',
  zones: 'H3 Zone Spatial Intelligence & Telemetry',
  models: 'Demand Forecasting Model Evaluation',
  surge: 'Persisted Surge Alerts & Capacity Deficits',
  system: 'System Health, Governance & Metadata'
};

/**
 * Top-level ErrorBoundary to prevent dynamic import or view exceptions
 * from leaving the application stuck in an unrecoverable loading state.
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('RideIntel Module ErrorBoundary caught an exception:', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 max-w-2xl mx-auto">
          <ErrorState
            title="Module Render Exception"
            message={this.state.error?.message || 'An unexpected error occurred while loading this view.'}
            onRetry={this.handleRetry}
          />
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [health, setHealth] = useState(null);
  const [metadata, setMetadata] = useState(null);

  useEffect(() => {
    let isMounted = true;

    async function loadInitialStatus() {
      try {
        const [h, m] = await Promise.all([
          fetchHealth().catch(() => ({ status: 'UNAVAILABLE' })),
          fetchMetadata().catch(() => null)
        ]);
        if (isMounted) {
          setHealth(h);
          setMetadata(m);
        }
      } catch {
        // Handled via catch blocks above
      }
    }

    loadInitialStatus();
    const interval = setInterval(loadInitialStatus, 30000); // 30s background poll

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex">
      {/* Persistent Navigation Sidebar */}
      <Sidebar activeTab={activeTab} onSelectTab={setActiveTab} />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen overflow-hidden">
        <Header
          title={TAB_TITLES[activeTab] || 'RideIntel Dashboard'}
          health={health}
          metadata={metadata}
        />

        {/* Viewport Router: Map-First Full Viewport vs Standard Dashboard Container */}
        {activeTab === 'map' ? (
          <main className="flex-1 w-full h-[calc(100vh-65px)] relative overflow-hidden">
            <ErrorBoundary>
              <Suspense fallback={<LoadingState message="Launching Fleet Simulation Command Centre..." />}>
                <ChicagoMapView onNavigateToZones={() => setActiveTab('zones')} />
              </Suspense>
            </ErrorBoundary>
          </main>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <main className="p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-6">
              <ErrorBoundary>
                <Suspense fallback={<LoadingState message="Loading module view..." />}>
                  {activeTab === 'overview' && (
                    <OverviewView
                      onNavigateToZones={() => setActiveTab('zones')}
                      onNavigateToMap={() => setActiveTab('map')}
                    />
                  )}
                  {activeTab === 'zones' && <ZoneIntelligenceView />}
                  {activeTab === 'models' && <ModelPerformanceView />}
                  {activeTab === 'surge' && <SurgeAlertsView />}
                  {activeTab === 'system' && <SystemStatusView />}
                </Suspense>
              </ErrorBoundary>
            </main>

            {/* Academic Prototype Footer (Non-map views) */}
            <footer className="border-t border-slate-900 bg-slate-950/60 px-8 py-4 text-xs text-slate-400 flex flex-col sm:flex-row items-center justify-between gap-2">
              <div>
                RideIntel &mdash; Chicago Ride Demand & Supply Intelligence &bull; June 2022 Academic Prototype
              </div>
              <div className="flex items-center gap-4 text-[11px] text-slate-400">
                <span>FastAPI Backend (Port 8000)</span>
                <span>&bull;</span>
                <span>Immutable Parquet Telemetry</span>
                <span>&bull;</span>
                <span>No Supabase / No Redis</span>
              </div>
            </footer>
          </div>
        )}
      </div>
    </div>
  );
}
