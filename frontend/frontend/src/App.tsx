import { Component, type ErrorInfo, type ReactNode } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./state/AppContext";
import { DashboardLayout } from "./components/layout/DashboardLayout";
import { Overview } from "./pages/Overview";
import { LiveMonitoring } from "./pages/LiveMonitoring";
import { RiskAlerts } from "./pages/RiskAlerts";
import { CustomAlerts } from "./pages/CustomAlerts";
import { GisIntelligence } from "./pages/GisIntelligence";
import { SensorNetwork } from "./pages/SensorNetwork";
import { FieldReports } from "./pages/FieldReports";
import { IncidentHistory } from "./pages/IncidentHistory";
import { ReportsAnalytics } from "./pages/ReportsAnalytics";
import { Settings } from "./pages/Settings";

/**
 * HashRouter is used so the built bundle also runs from a static file server or a plain
 * folder without server-side rewrite rules — useful for an offline on a laptop.
 * Swap for BrowserRouter when it is deployed behind a real host.
 */
export function App() {
  return (
    <ErrorBoundary>
      <AppProvider>
        <HashRouter>
          <DashboardLayout>
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/live" element={<LiveMonitoring />} />
              <Route path="/alerts" element={<RiskAlerts />} />
              <Route path="/custom-alerts" element={<CustomAlerts />} />
              <Route path="/gis" element={<GisIntelligence />} />
              <Route path="/sensors" element={<SensorNetwork />} />
              <Route path="/field-reports" element={<FieldReports />} />
              <Route path="/incidents" element={<IncidentHistory />} />
              <Route path="/reports" element={<ReportsAnalytics />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </DashboardLayout>
        </HashRouter>
      </AppProvider>
    </ErrorBoundary>
  );
}

/** A dashboard used in an emergency must degrade to a readable message, never a white screen. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard error", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32, maxWidth: 620, margin: "0 auto" }}>
          <h1 style={{ fontSize: 20 }}>The dashboard hit an unexpected error</h1>
          <p className="muted" style={{ fontSize: 13 }}>
            {this.state.error.message}
          </p>
          <button className="btn primary" type="button" onClick={() => window.location.reload()}>
            Reload the application
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
