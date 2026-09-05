import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { GISLayerId, RiskZone } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { alertService, gisService, riskService, sensorService, weatherService } from "@/services";
import { PageHeader, PipelineStrip } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, KpiCard, RiskBadge } from "@/components/ui/primitives";
import { RiskMap, type MapSelection } from "@/components/map/RiskMap";
import { MapLayerControl, ZoneDetailPanel } from "@/components/map/MapPanels";
import { EmergencyBanner } from "@/components/alerts/AlertCard";
import { WeatherPanel } from "@/components/weather/WeatherPanel";
import { LineChart } from "@/components/charts";
import { compactNumber, relativeTime, riskVar } from "@/utils";

const OVERVIEW_LAYERS: GISLayerId[] = ["risk_heatmap", "sensors", "roads"];

export function Overview() {
  const app = useApp();
  const navigate = useNavigate();
  const [layers, setLayers] = useState<Set<GISLayerId>>(new Set(OVERVIEW_LAYERS));
  const [selection, setSelection] = useState<MapSelection | null>(null);

  const summary = useAsync(() => riskService.getRiskSummary(app.scope), [app.stateCode, app.districtId]);
  const zones = useAsync(() => riskService.getRiskZones(app.scope), [app.stateCode, app.districtId]);
  const alerts = useAsync(() => alertService.getActiveAlerts(app.scope), [app.stateCode, app.districtId]);
  const sensors = useAsync(() => sensorService.getSensors(app.scope), [app.stateCode, app.districtId]);
  const roads = useAsync(() => gisService.getRoads(app.scope), [app.stateCode, app.districtId]);
  const weather = useAsync(() => weatherService.getWeather(app.scope), [app.districtId]);
  const trend = useAsync(
    () => riskService.getRiskTrend(app.districtId === "ALL" ? "ALL" : app.districtId, 30),
    [app.districtId],
  );
  const pipeline = useAsync(() => riskService.getPipelineHealth(app.scope), [app.stateCode, app.districtId]);

  const criticalAlert = alerts.data?.find((a) => a.severity === "CRITICAL");
  const selectedZone: RiskZone | null =
    selection?.kind === "zone" ? zones.data?.find((z) => z.id === selection.id) ?? null : null;

  const toggleLayer = (id: GISLayerId) =>
    setLayers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const topZones = useMemo(() => (zones.data ?? []).slice(0, 6), [zones.data]);

  return (
    <>
      <PageHeader
        title="NER Landslide Early Warning System"
        subtitle="Real-time landslide risk monitoring and early warning intelligence"
        updatedAt={summary.data?.updatedAt}
        freshnessMinutes={summary.data?.dataFreshnessMinutes}
        actions={
          <>
            <button className="btn sm" type="button" onClick={() => { summary.reload(); zones.reload(); alerts.reload(); }}>
              Refresh
            </button>
            <Link className="btn sm primary" to="/alerts">
              Alert centre
            </Link>
          </>
        }
      />

      <div className="stack">
        {criticalAlert && (
          <EmergencyBanner
            alert={criticalAlert}
            onViewMap={() => {
              setSelection({ kind: "zone", id: criticalAlert.zoneId });
              document.getElementById("overview-map")?.scrollIntoView({ behavior: "smooth", block: "center" });
            }}
            onAcknowledge={async () => {
              await alertService.acknowledgeAlert(criticalAlert.id);
              alerts.reload();
              app.toast({ tone: "success", title: `${criticalAlert.id} acknowledged` });
            }}
            onDispatch={async () => {
              await alertService.dispatchResponse(criticalAlert.id);
              alerts.reload();
              app.toast({
                tone: "warning",
                title: "Response dispatched",
                body: "Alert moved to in-progress and warnings re-sent to the tier audience.",
              });
            }}
            onDetails={() => navigate("/alerts")}
          />
        )}

        {/* KPI band */}
        <AsyncSection state={summary} loadingLabel="Loading regional summary…" rows={2}>
          {(s) => (
            <div className="grid grid-kpi">
              <KpiCard
                label="Active alerts"
                value={s.activeAlerts}
                level={s.criticalAlerts > 0 ? "CRITICAL" : s.activeAlerts > 0 ? "HIGH" : "LOW"}
                note={`${s.criticalAlerts} critical`}
                onClick={() => navigate("/alerts")}
              />
              <KpiCard
                label="High-risk zones"
                value={s.highRiskZones}
                note={`of ${s.totalZones} monitored zones`}
                level={s.highRiskZones > 0 ? "HIGH" : "LOW"}
                onClick={() => navigate("/gis")}
              />
              <KpiCard
                label="Sensors online"
                value={s.sensorsOnline}
                note={`${s.sensorsDegraded} degraded`}
                onClick={() => navigate("/sensors")}
              />
              <KpiCard
                label="Sensors offline"
                value={s.sensorsOffline}
                level={s.sensorsOffline > 0 ? "MODERATE" : "LOW"}
                note="No data reaching the risk engine"
                onClick={() => navigate("/sensors")}
              />
              <KpiCard
                label="Blocked / at-risk roads"
                value={`${s.blockedRoads} / ${s.atRiskRoads}`}
                note="blocked / restricted or at risk"
                level={s.blockedRoads > 0 ? "HIGH" : "MODERATE"}
              />
              <KpiCard
                label="Regional risk score"
                value={s.regionalRiskScore}
                unit="/100"
                level={s.regionalRiskLevel}
                note="Peak-weighted across zones in scope"
              />
              <KpiCard
                label="Reports pending verification"
                value={s.reportsPendingVerification}
                note="Citizen and field submissions"
                onClick={() => navigate("/field-reports")}
              />
              <KpiCard
                label="Weather risk"
                value={s.weatherRiskLevel}
                level={s.weatherRiskLevel}
                note={`${compactNumber(s.populationExposed)} people in high-risk zones`}
              />
            </div>
          )}
        </AsyncSection>

        {/* pipeline */}
        <AsyncSection state={pipeline} loadingLabel="Loading pipeline status…" rows={1}>
          {(p) => (
            <PipelineStrip
              steps={[
                { name: "Sensors reporting", value: `${p.sensorsReporting}/${p.sensorsTotal}`, to: "/sensors" },
                { name: "Mean sensor health", value: `${p.meanSensorHealth}/100`, to: "/sensors" },
                { name: "Zones scored", value: `${p.zonesScored}`, to: "/live" },
                { name: "Score confidence", value: `${p.meanConfidence}/100`, to: "/sensors" },
                { name: "Active alerts", value: `${alerts.data?.length ?? 0}`, to: "/alerts" },
                { name: "Events pre-alerted", value: `${p.eventsPrecededByAlert}%`, to: "/reports" },
              ]}
            />
          )}
        </AsyncSection>

        {/* map + side rail */}
        <div className="grid grid-main" id="overview-map">
          <section className="card">
            <header className="card-head">
              <div>
                <h2>Live risk map</h2>
                <div className="hint">Where is the danger right now — {app.scopeLabel}</div>
              </div>
              <div className="row">
                <div className="segmented">
                  {(["risk_heatmap", "sensors", "roads"] as GISLayerId[]).map((id) => (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={layers.has(id)}
                      onClick={() => toggleLayer(id)}
                    >
                      {id === "risk_heatmap" ? "Risk" : id === "sensors" ? "Sensors" : "Roads"}
                    </button>
                  ))}
                </div>
                <Link className="btn sm" to="/gis">
                  Full GIS
                </Link>
              </div>
            </header>
            <AsyncSection
              state={zones}
              loadingLabel="Loading risk zones…"
              emptyTitle="No zones in this scope"
              emptyHint="Select a different state or district."
              isEmpty={(z) => z.length === 0}
              rows={4}
            >
              {(z) => (
                <RiskMap
                  zones={z}
                  sensors={sensors.data ?? []}
                  roads={roads.data ?? []}
                  activeLayers={layers}
                  selected={selection}
                  onSelect={setSelection}
                  height={430}
                />
              )}
            </AsyncSection>
          </section>

          <div className="stack">
            <Card title="Highest-risk zones" subtitle="Ranked by model score">
              <AsyncSection
                state={zones}
                loadingLabel="Scoring zones…"
                emptyTitle="No zones scored"
                isEmpty={(z) => z.length === 0}
              >
                {() => (
                  <div className="stack" style={{ gap: 7 }}>
                    {topZones.map((z) => (
                      <button
                        key={z.id}
                        type="button"
                        className="row between"
                        onClick={() => setSelection({ kind: "zone", id: z.id })}
                        style={{
                          background: "none",
                          border: 0,
                          borderBottom: "1px solid var(--line)",
                          padding: "5px 0",
                          cursor: "pointer",
                          textAlign: "left",
                          width: "100%",
                        }}
                      >
                        <span style={{ minWidth: 0 }}>
                          <span style={{ display: "block", fontSize: 12.5, fontWeight: 500 }}>{z.name}</span>
                          <span className="tiny muted">
                            {z.district} · {relativeTime(z.updatedAt)}
                          </span>
                        </span>
                        <span className="row" style={{ gap: 7 }}>
                          <span className="mono" style={{ color: riskVar(z.riskLevel), fontWeight: 600 }}>
                            {z.riskScore}
                          </span>
                          <RiskBadge level={z.riskLevel} />
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </AsyncSection>
            </Card>

            <Card title="Weather" subtitle="Weather-linked landslide risk">
              <AsyncSection state={weather} loadingLabel="Fetching conditions…">
                {(w) => <WeatherPanel weather={w} compact />}
              </AsyncSection>
            </Card>

            <Card title="Map layers">
              <div style={{ margin: "-14px -16px" }}>
                <MapLayerControl active={layers} onToggle={toggleLayer} compact />
              </div>
            </Card>
          </div>
        </div>

        {/* trend + roads */}
        <div className="grid grid-2 grid-1-mobile">
          <Card title="Regional risk trend" subtitle="Model score vs rainfall · last 30 days">
            <AsyncSection state={trend} loadingLabel="Loading trend…" isEmpty={(t) => t.length === 0}>
              {(t) => (
                <LineChart
                  title="Risk score and rainfall over the last 30 days"
                  labels={t.map((p) => new Date(p.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }))}
                  series={[
                    { label: "Risk score", color: "var(--high)", values: t.map((p) => p.riskScore), fill: true },
                    { label: "Rainfall (mm)", color: "var(--info)", values: t.map((p) => p.rainfall) },
                  ]}
                  yMax={200}
                />
              )}
            </AsyncSection>
          </Card>

          <Card title="Road connectivity" subtitle="Status of monitored corridors">
            <AsyncSection
              state={roads}
              loadingLabel="Loading road status…"
              emptyTitle="No monitored roads in scope"
              isEmpty={(r) => r.length === 0}
            >
              {(r) => (
                <div className="table-wrap">
                  <table className="data" style={{ minWidth: 420 }}>
                    <thead>
                      <tr>
                        <th scope="col">Road</th>
                        <th scope="col">Status</th>
                        <th scope="col">Risk</th>
                        <th scope="col">Updated</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.slice(0, 8).map((road) => (
                        <tr key={road.id}>
                          <td>
                            {road.name}
                            {road.note && <div className="tiny muted">{road.note}</div>}
                          </td>
                          <td>
                            <span
                              className="badge sq"
                              style={{
                                background: road.status === "OPEN" ? "var(--low-bg)" : "var(--surface-2)",
                                color:
                                  road.status === "BLOCKED"
                                    ? "var(--sev)"
                                    : road.status === "RESTRICTED"
                                      ? "var(--high)"
                                      : road.status === "AT_RISK"
                                        ? "var(--mod)"
                                        : "var(--low)",
                                borderColor: "var(--line)",
                              }}
                            >
                              {road.status.replace("_", " ")}
                            </span>
                          </td>
                          <td>
                            <RiskBadge level={road.riskLevel} />
                          </td>
                          <td className="mono tiny">{relativeTime(road.lastUpdated)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {r.length === 0 && <EmptyState title="No roads monitored" />}
                </div>
              )}
            </AsyncSection>
          </Card>
        </div>

      </div>

      <ZoneDetailPanel
        zone={selectedZone}
        sensors={sensors.data ?? []}
        open={Boolean(selectedZone)}
        onClose={() => setSelection(null)}
        onViewAlerts={() => navigate("/alerts")}
        onOpenGis={() => navigate("/gis")}
      />
    </>
  );
}
