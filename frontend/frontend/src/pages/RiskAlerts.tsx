import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { Alert, AlertSeverity } from "@/types";
import { useApp, districtsInScope } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { alertService, riskService, sensorService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, DefRow, Drawer, EmptyState, RiskBadge } from "@/components/ui/primitives";
import { AlertCard, EmergencyBanner } from "@/components/alerts/AlertCard";
import { BarChart } from "@/components/charts";
import { RiskMap } from "@/components/map/RiskMap";
import { SEVERITY_ORDER, formatDateTime, matchesQuery, riskVar, sortBy, titleCase } from "@/utils";

const TABS: (AlertSeverity | "ALL")[] = ["ALL", "CRITICAL", "HIGH", "MODERATE", "INFORMATION"];
type SortMode = "severity" | "recent" | "score";

export function RiskAlerts() {
  const app = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const [tab, setTab] = useState<AlertSeverity | "ALL">("ALL");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [districtFilter, setDistrictFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [fromDate, setFromDate] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("severity");
  const [detail, setDetail] = useState<Alert | null>(null);
  const [mapAlert, setMapAlert] = useState<Alert | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const alerts = useAsync(() => alertService.getAlerts(app.scope), [app.stateCode, app.districtId]);
  const zones = useAsync(() => riskService.getRiskZones(app.scope), [app.stateCode, app.districtId]);
  const sensors = useAsync(() => sensorService.getSensors(app.scope), [app.stateCode, app.districtId]);

  const districts = districtsInScope(app.stateCode);

  const filtered = useMemo(() => {
    let list = alerts.data ?? [];
    if (tab !== "ALL") list = list.filter((a) => a.severity === tab);
    if (districtFilter !== "ALL") list = list.filter((a) => a.districtId === districtFilter);
    if (statusFilter !== "ALL") list = list.filter((a) => a.status === statusFilter);
    if (fromDate) {
      const from = new Date(fromDate).getTime();
      list = list.filter((a) => new Date(a.issuedAt).getTime() >= from);
    }
    if (query.trim()) {
      list = list.filter((a) =>
        matchesQuery(query, a.id, a.location, a.district, a.title, a.affectedRoads.join(" "), a.affectedVillages.join(" ")),
      );
    }
    if (sortMode === "recent") return sortBy(list, (a) => new Date(a.issuedAt).getTime(), "desc");
    if (sortMode === "score") return sortBy(list, (a) => a.riskScore, "desc");
    return sortBy(list, (a) => SEVERITY_ORDER[a.severity] * 1000 + a.riskScore, "desc");
  }, [alerts.data, tab, districtFilter, statusFilter, fromDate, query, sortMode]);

  const critical = (alerts.data ?? []).find((a) => a.severity === "CRITICAL" && a.status !== "RESOLVED");

  const counts = useMemo(() => {
    const list = alerts.data ?? [];
    return {
      CRITICAL: list.filter((a) => a.severity === "CRITICAL").length,
      HIGH: list.filter((a) => a.severity === "HIGH").length,
      MODERATE: list.filter((a) => a.severity === "MODERATE").length,
      INFORMATION: list.filter((a) => a.severity === "INFORMATION").length,
    };
  }, [alerts.data]);

  const act = async (a: Alert, kind: "ack" | "dispatch") => {
    setBusyId(a.id);
    try {
      if (kind === "ack") {
        await alertService.acknowledgeAlert(a.id);
        app.toast({ tone: "success", title: `${a.id} acknowledged`, body: `${a.district} — logged against the duty officer.` });
      } else {
        await alertService.dispatchResponse(a.id);
        app.toast({
          tone: "warning",
          title: `Response dispatched for ${a.id}`,
          body: "Moved to in-progress. Warnings re-sent to the recipients for this tier.",
        });
      }
      alerts.reload();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Risk &amp; Alerts"
        subtitle="Active warnings, acknowledgement status and recommended action"
        updatedAt={alerts.fetchedAt}
        actions={
          <button className="btn sm" type="button" onClick={() => alerts.reload()}>
            Refresh
          </button>
        }
      />

      <div className="stack">
        {critical && (
          <EmergencyBanner
            alert={critical}
            onViewMap={() => setMapAlert(critical)}
            onAcknowledge={() => void act(critical, "ack")}
            onDispatch={() => void act(critical, "dispatch")}
            onDetails={() => setDetail(critical)}
          />
        )}

        <div className="grid grid-2 grid-1-mobile">
          <Card title="Alerts by severity" subtitle="Current scope">
            <AsyncSection state={alerts} loadingLabel="Loading alerts…" isEmpty={(a) => a.length === 0}>
              {() => (
                <BarChart
                  title="Alert count by severity"
                  height={168}
                  data={[
                    { label: "Critical", value: counts.CRITICAL, color: "var(--sev)" },
                    { label: "High", value: counts.HIGH, color: "var(--high)" },
                    { label: "Moderate", value: counts.MODERATE, color: "var(--mod)" },
                    { label: "Information", value: counts.INFORMATION, color: "var(--ink-4)" },
                  ]}
                />
              )}
            </AsyncSection>
          </Card>

          <Card title="Alert locations" subtitle="Click a zone to inspect it on the GIS page">
            <AsyncSection state={zones} loadingLabel="Loading map…" isEmpty={(z) => z.length === 0}>
              {(z) => (
                <RiskMap
                  zones={z.filter((zone) => (alerts.data ?? []).some((a) => a.zoneId === zone.id))}
                  activeLayers={new Set(["risk_heatmap"])}
                  height={190}
                  showStateLabels={false}
                  onSelect={() => navigate("/gis")}
                />
              )}
            </AsyncSection>
          </Card>
        </div>

        <section className="card">
          <div className="toolbar">
            <div className="segmented" role="tablist" aria-label="Filter by severity">
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  aria-pressed={tab === t}
                  onClick={() => setTab(t)}
                >
                  {t}
                  {t !== "ALL" && <span className="mono"> {counts[t]}</span>}
                </button>
              ))}
            </div>

            <input
              type="search"
              placeholder="Search alerts, roads, villages…"
              aria-label="Search alerts"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setParams(e.target.value ? { q: e.target.value } : {});
              }}
              style={{ flex: "1 1 190px" }}
            />

            <select value={districtFilter} onChange={(e) => setDistrictFilter(e.target.value)} aria-label="Filter by district">
              <option value="ALL">All districts</option>
              {districts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>

            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
              <option value="ALL">Any status</option>
              <option value="NEW">New</option>
              <option value="ACKNOWLEDGED">Acknowledged</option>
              <option value="IN_PROGRESS">In progress</option>
              <option value="RESOLVED">Resolved</option>
            </select>

            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              aria-label="Issued on or after"
              title="Issued on or after"
            />

            <select value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)} aria-label="Sort alerts">
              <option value="severity">Sort: severity</option>
              <option value="recent">Sort: most recent</option>
              <option value="score">Sort: risk score</option>
            </select>

            {(query || districtFilter !== "ALL" || statusFilter !== "ALL" || fromDate || tab !== "ALL") && (
              <button
                className="btn sm ghost"
                type="button"
                onClick={() => {
                  setQuery("");
                  setDistrictFilter("ALL");
                  setStatusFilter("ALL");
                  setFromDate("");
                  setTab("ALL");
                  setParams({});
                }}
              >
                Clear filters
              </button>
            )}
          </div>

          <div className="card-body">
            <AsyncSection
              state={alerts}
              loadingLabel="Loading alerts…"
              emptyTitle="No active alerts"
              emptyHint="Conditions in this scope are below the alerting threshold."
              isEmpty={() => filtered.length === 0}
              rows={5}
            >
              {() =>
                filtered.length === 0 ? (
                  <EmptyState title="No alerts match these filters" hint="Try clearing the search or date filter." />
                ) : (
                  <div className="stack">
                    {filtered.map((a) => (
                      <AlertCard
                        key={a.id}
                        alert={a}
                        busy={busyId === a.id}
                        onViewMap={setMapAlert}
                        onAcknowledge={(x) => void act(x, "ack")}
                        onDispatch={(x) => void act(x, "dispatch")}
                        onDetails={setDetail}
                      />
                    ))}
                  </div>
                )
              }
            </AsyncSection>
          </div>
        </section>
      </div>

      {/* alert detail */}
      <Drawer
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={detail ? `${detail.id} · ${detail.title}` : ""}
        subtitle={detail ? `${detail.location} · ${detail.district}` : undefined}
        labelledBy="alert-detail-title"
        footer={
          detail && (
            <>
              <button className="btn primary" type="button" onClick={() => void act(detail, "dispatch")}>
                Dispatch response
              </button>
              <button className="btn" type="button" onClick={() => { setMapAlert(detail); setDetail(null); }}>
                View on map
              </button>
            </>
          )
        }
      >
        {detail && (
          <>
            <div className="row between" style={{ marginBottom: 10 }}>
              <RiskBadge level={detail.severity} />
              <span className="mono" style={{ fontSize: 22, fontWeight: 600, color: riskVar(detail.severity) }}>
                {detail.riskScore}
              </span>
            </div>
            <dl className="dl">
              <DefRow label="Alert ID">{detail.id}</DefRow>
              <DefRow label="Issued">{formatDateTime(detail.issuedAt)}</DefRow>
              <DefRow label="Status">{titleCase(detail.status)}</DefRow>
              <DefRow label="Probability">{(detail.probability * 100).toFixed(1)}%</DefRow>
              <DefRow label="Expected window">next {detail.expectedWindowHours} h</DefRow>
              <DefRow label="Trigger">{titleCase(detail.trigger)}</DefRow>
              <DefRow label="Sensor confidence">{detail.sensorConfidence}/100</DefRow>
              <DefRow label="Population">{detail.populationAffected.toLocaleString("en-IN")}</DefRow>
              <DefRow label="Acknowledged by">{detail.acknowledgedBy ?? "—"}</DefRow>
            </dl>
            <div className="callout info" style={{ marginTop: 12 }}>
              {detail.triggerDetail}
            </div>
            <h3 style={{ fontSize: 12.5, margin: "14px 0 5px" }}>Affected roads</h3>
            <div className="tag-list">
              {detail.affectedRoads.map((r) => (
                <span className="tag" key={r}>
                  {r}
                </span>
              ))}
            </div>
            <h3 style={{ fontSize: 12.5, margin: "14px 0 5px" }}>Affected villages</h3>
            <div className="tag-list">
              {detail.affectedVillages.map((v) => (
                <span className="tag" key={v}>
                  {v}
                </span>
              ))}
            </div>
            <div className="recommend" style={{ marginTop: 14 }}>
              {detail.recommendedAction}
            </div>
            <div className="disclaimer">
              Demonstration alert generated from synthetic sensor and rainfall values.
            </div>
          </>
        )}
      </Drawer>

      {/* map focus */}
      <Drawer
        open={Boolean(mapAlert)}
        onClose={() => setMapAlert(null)}
        title={mapAlert ? `Map · ${mapAlert.location}` : ""}
        subtitle={mapAlert?.district}
        labelledBy="alert-map-title"
      >
        {mapAlert && zones.data && (
          <>
            <RiskMap
              zones={zones.data.filter((z) => z.id === mapAlert.zoneId)}
              sensors={(sensors.data ?? []).filter((s) => s.zoneId === mapAlert.zoneId)}
              activeLayers={new Set(["risk_heatmap", "sensors"])}
              height={260}
              showStateLabels={false}
            />
            <div className="tiny muted" style={{ marginTop: 8 }}>
              Schematic view. Open GIS Intelligence for terrain, exposure and 3D context.
            </div>
            <button className="btn block" type="button" style={{ marginTop: 10 }} onClick={() => navigate("/gis")}>
              Open GIS Intelligence
            </button>
          </>
        )}
      </Drawer>
    </>
  );
}
