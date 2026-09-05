import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { Alert, AlertSeverity } from "@/types";
import { useApp, districtsInScope } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { alertService, riskService, sensorService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, DefRow, Drawer, RiskBadge } from "@/components/ui/primitives";
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
        if (a.status === "ACKNOWLEDGED") {
          await alertService.unacknowledgeAlert(a.id);
          app.toast({ tone: "info", title: `${a.id} reset to Unacknowledged` });
        } else {
          await alertService.acknowledgeAlert(a.id);
          app.toast({ tone: "success", title: `${a.id} acknowledged`, body: `${a.district} logged against duty officer.` });
        }
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

        {/* tab strip + filters */}
        <div className="card pad">
          <div className="row between" style={{ gap: 12 }}>
            <div className="segmented overflow-x">
              {TABS.map((t) => (
                <button key={t} type="button" aria-pressed={tab === t} onClick={() => setTab(t)}>
                  {t === "ALL" ? `All (${alerts.data?.length ?? 0})` : `${titleCase(t)} (${counts[t]})`}
                </button>
              ))}
            </div>

            <div className="row" style={{ gap: 8 }}>
              <input
                type="search"
                placeholder="Search alerts, locations…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setParams((p) => {
                    if (e.target.value) p.set("q", e.target.value);
                    else p.delete("q");
                    return p;
                  });
                }}
                style={{ width: 220 }}
              />
              <select value={districtFilter} onChange={(e) => setDistrictFilter(e.target.value)}>
                <option value="ALL">All districts ({districts.length})</option>
                {districts.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="ALL">All statuses</option>
                <option value="NEW">New</option>
                <option value="ACKNOWLEDGED">Acknowledged</option>
                <option value="IN_PROGRESS">In-progress</option>
                <option value="RESOLVED">Resolved</option>
              </select>
              <input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                title="From date"
              />
              <select value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)}>
                <option value="severity">Sort by severity</option>
                <option value="recent">Sort by recent</option>
                <option value="score">Sort by risk score</option>
              </select>
            </div>
          </div>
        </div>

        {/* alert list */}
        <AsyncSection
          state={alerts}
          loadingLabel="Loading alert feed…"
          emptyTitle="No alerts match the active filters"
          emptyHint="Try clearing the search or severity filter."
          isEmpty={() => filtered.length === 0}
          rows={3}
        >
          {() => (
            <div className="stack" style={{ gap: 10 }}>
              {filtered.map((a) => (
                <AlertCard
                  key={a.id}
                  alert={a}
                  busy={busyId === a.id}
                  onAcknowledge={(alert) => void act(alert, "ack")}
                  onDispatch={(alert) => void act(alert, "dispatch")}
                  onViewMap={(alert) => setMapAlert(alert)}
                  onDetails={(alert) => setDetail(alert)}
                />
              ))}
            </div>
          )}
        </AsyncSection>
      </div>

      {/* alert detail */}
      <Drawer open={Boolean(detail)} onClose={() => setDetail(null)} title={detail?.title ?? "Alert details"}>
        {detail && (
          <>
            <div className="row between" style={{ marginBottom: 10 }}>
              <RiskBadge level={detail.severity} />
              <span className="mono" style={{ fontSize: 22, color: riskVar(detail.severity), fontWeight: 600 }}>
                {detail.riskScore}
                <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
                  /100
                </span>
              </span>
            </div>

            <dl className="dl">
              <DefRow label="Alert ID">{detail.id}</DefRow>
              <DefRow label="District">{detail.district}</DefRow>
              <DefRow label="Location">{detail.location}</DefRow>
              <DefRow label="Status">{detail.status}</DefRow>
              <DefRow label="Trigger">{titleCase(detail.trigger)}</DefRow>
              <DefRow label="Issued">{formatDateTime(detail.issuedAt)}</DefRow>
              <DefRow label="Acknowledged by">{detail.acknowledgedBy ?? "Not acknowledged"}</DefRow>
              <DefRow label="Sensor confidence">{detail.sensorConfidence}/100</DefRow>
              <DefRow label="Population exposed">{detail.populationAffected.toLocaleString("en-IN")}</DefRow>
            </dl>

            <h3 style={{ fontSize: 12.5, margin: "14px 0 5px" }}>Trigger detail</h3>
            <div className="tiny muted">{detail.triggerDetail}</div>

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
          </>
        )}
      </Drawer>

      {/* map focus */}
      <Drawer
        open={Boolean(mapAlert)}
        onClose={() => setMapAlert(null)}
        title={mapAlert ? `Map: ${mapAlert.location}` : ""}
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
              Open GIS Intelligence for terrain, exposure and 3D context.
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
