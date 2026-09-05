import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { GISLayerId, RiskZone } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { alertService, gisService, riskService, sensorService, weatherService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, RiskBadge } from "@/components/ui/primitives";
import { RiskMap, type MapSelection } from "@/components/map/RiskMap";
import { ZoneDetailPanel } from "@/components/map/MapPanels";
import { EmergencyBanner } from "@/components/alerts/AlertCard";
import { WeatherPanel } from "@/components/weather/WeatherPanel";
import { LineChart } from "@/components/charts";
import { relativeTime, riskVar } from "@/utils";

const OVERVIEW_LAYERS: GISLayerId[] = ["risk_heatmap", "sensors", "roads"];

const ALL_MAP_LAYERS: { id: GISLayerId; label: string }[] = [
  { id: "risk_heatmap", label: "Risk heatmap" },
  { id: "sensors", label: "Sensors" },
  { id: "roads", label: "Roads" },
  { id: "settlements", label: "Villages" },
  { id: "infrastructure", label: "Infrastructure" },
  { id: "incidents", label: "Reported incidents" },
  { id: "rainfall", label: "Rainfall" },
  { id: "terrain", label: "Terrain shading" },
  { id: "satellite", label: "Satellite imagery" },
];

function LayerDropdown({
  active,
  onToggle,
}: {
  active: Set<GISLayerId>;
  onToggle: (id: GISLayerId) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        className="btn sm"
        onClick={() => setOpen((prev) => !prev)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontWeight: 500,
          background: open ? "var(--surface-2)" : undefined,
        }}
      >
        <span>Layers ({active.size})</span>
        <span style={{ fontSize: 10 }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 1002,
            background: "#ffffff",
            border: "1px solid var(--line)",
            borderRadius: "var(--r)",
            boxShadow: "0 10px 30px rgba(0,0,0,0.15)",
            padding: "10px 14px",
            minWidth: "220px",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "var(--ink-3)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              marginBottom: 4,
              borderBottom: "1px solid var(--line-2)",
              paddingBottom: 4,
            }}
          >
            Map Layers
          </div>
          {ALL_MAP_LAYERS.map((layer) => {
            const isChecked = active.has(layer.id);
            return (
              <label
                key={layer.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  cursor: "pointer",
                  padding: "3px 4px",
                  borderRadius: "var(--r-sm)",
                  userSelect: "none",
                }}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggle(layer.id)}
                  style={{
                    accentColor: "var(--geo)",
                    width: 16,
                    height: 16,
                    cursor: "pointer",
                  }}
                />
                <span style={{ color: isChecked ? "var(--ink)" : "var(--ink-2)" }}>
                  {layer.label}
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
  const villages = useAsync(() => gisService.getVillages(app.scope), [app.stateCode, app.districtId]);
  const infrastructure = useAsync(
    () => gisService.getInfrastructure(app.scope),
    [app.stateCode, app.districtId],
  );
  const weather = useAsync(() => weatherService.getWeather(app.scope), [app.districtId]);
  const trend = useAsync(
    () => riskService.getRiskTrend(app.districtId === "ALL" ? "ALL" : app.districtId, 30),
    [app.districtId],
  );

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
            viewMapLabel="Overview"
            onViewMap={() => {
              setSelection({ kind: "zone", id: criticalAlert.zoneId });
              document.getElementById("overview-map")?.scrollIntoView({ behavior: "smooth", block: "center" });
            }}
            onAcknowledge={async () => {
              if (criticalAlert.status === "ACKNOWLEDGED") {
                await alertService.unacknowledgeAlert(criticalAlert.id);
                alerts.reload();
                app.toast({ tone: "info", title: `${criticalAlert.id} reset to Unacknowledged` });
              } else {
                await alertService.acknowledgeAlert(criticalAlert.id);
                alerts.reload();
                app.toast({ tone: "success", title: `${criticalAlert.id} acknowledged` });
              }
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

        {/* map + side rail */}
        <div className="grid grid-main" id="overview-map">
          <section className="card" style={{ display: "flex", flexDirection: "column" }}>
            <header className="card-head">
              <div>
                <h2>Live risk map</h2>
                <div className="hint">Where is the danger right now: {app.scopeLabel}</div>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <LayerDropdown active={layers} onToggle={toggleLayer} />
                <Link className="btn sm" to="/gis">
                  Full GIS
                </Link>
              </div>
            </header>
            <div style={{ flex: 1, minHeight: 460, position: "relative" }}>
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
                    villages={villages.data ?? []}
                    infrastructure={infrastructure.data ?? []}
                    activeLayers={layers}
                    selected={selection}
                    onSelect={setSelection}
                    height="100%"
                  />
                )}
              </AsyncSection>
            </div>
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
