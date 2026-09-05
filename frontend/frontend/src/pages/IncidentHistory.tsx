import { useMemo, useState } from "react";
import type { HistoricalIncident, IncidentType, RiskLevel } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { incidentService, riskService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, EmptyState, KpiCard, RiskBadge } from "@/components/ui/primitives";
import { RiskMap } from "@/components/map/RiskMap";
import { RISK_ORDER, formatDate, matchesQuery, sortBy, titleCase } from "@/utils";

type ViewMode = "TABLE" | "TIMELINE" | "MAP";
type SortKey = "date" | "severity" | "riskScoreAtEvent" | "responseTimeMinutes" | "affectedPopulation";

const TYPES: IncidentType[] = [
  "LANDSLIDE",
  "ROCKFALL",
  "CRACK",
  "ROAD_BLOCKAGE",
  "SLOPE_MOVEMENT",
  "FLOOD",
  "OTHER",
];

export function IncidentHistory() {
  const app = useApp();
  const [view, setView] = useState<ViewMode>("TABLE");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<IncidentType | "ALL">("ALL");
  const [severity, setSeverity] = useState<RiskLevel | "ALL">("ALL");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  const incidents = useAsync(() => incidentService.getIncidents(app.scope), [app.stateCode, app.districtId]);
  const zones = useAsync(() => riskService.getRiskZones(app.scope), [app.stateCode, app.districtId]);

  const filtered = useMemo(() => {
    let list = incidents.data ?? [];
    if (type !== "ALL") list = list.filter((i) => i.incidentType === type);
    if (severity !== "ALL") list = list.filter((i) => i.severity === severity);
    if (from) list = list.filter((i) => new Date(i.date).getTime() >= new Date(from).getTime());
    if (to) list = list.filter((i) => new Date(i.date).getTime() <= new Date(to).getTime());
    if (query.trim()) list = list.filter((i) => matchesQuery(query, i.id, i.location, i.district, i.affectedRoad));
    return sortBy(
      list,
      (i) =>
        sortKey === "date"
          ? new Date(i.date).getTime()
          : sortKey === "severity"
            ? RISK_ORDER[i.severity]
            : (i[sortKey] as number),
      dir,
    );
  }, [incidents.data, type, severity, from, to, query, sortKey, dir]);

  const stats = useMemo(() => {
    const list = filtered;
    const predicted = list.filter((i) => i.predicted).length;
    return {
      total: list.length,
      predicted,
      detectionRate: list.length ? Math.round((predicted / list.length) * 100) : 0,
      meanResponse: list.length
        ? Math.round(list.reduce((a, i) => a + i.responseTimeMinutes, 0) / list.length)
        : 0,
      population: list.reduce((a, i) => a + i.affectedPopulation, 0),
    };
  }, [filtered]);

  const th = (key: SortKey, label: string) => (
    <th scope="col" aria-sort={sortKey === key ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => {
          if (sortKey === key) setDir(dir === "asc" ? "desc" : "asc");
          else {
            setSortKey(key);
            setDir("desc");
          }
        }}
      >
        {label}
        <span aria-hidden="true">{sortKey === key ? (dir === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );

  return (
    <>
      <PageHeader
        title="Incident History"
        subtitle="Recorded events, response performance and whether the platform saw them coming"
        updatedAt={incidents.fetchedAt}
        actions={
          <div className="segmented">
            {(["TABLE", "TIMELINE", "MAP"] as ViewMode[]).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>
                {titleCase(v)}
              </button>
            ))}
          </div>
        }
      />

      <div className="stack">
        <div className="grid grid-4">
          <KpiCard label="Recorded events" value={stats.total} note="Matching current filters" />
          <KpiCard
            label="Preceded by an alert"
            value={`${stats.detectionRate}%`}
            note={`${stats.predicted} of ${stats.total} events`}
            level={stats.detectionRate >= 70 ? "LOW" : stats.detectionRate >= 45 ? "MODERATE" : "HIGH"}
          />
          <KpiCard label="Mean response time" value={stats.meanResponse} unit=" min" note="First responder on site" />
          <KpiCard label="Population affected" value={stats.population.toLocaleString("en-IN")} />
        </div>

        <section className="card">
          <div className="toolbar">
            <input
              type="search"
              placeholder="Search location, road or incident ID…"
              aria-label="Search incidents"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ flex: "1 1 190px" }}
            />
            <select value={type} onChange={(e) => setType(e.target.value as IncidentType | "ALL")} aria-label="Incident type">
              <option value="ALL">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {titleCase(t)}
                </option>
              ))}
            </select>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as RiskLevel | "ALL")} aria-label="Severity">
              <option value="ALL">Any severity</option>
              {(["CRITICAL", "HIGH", "MODERATE", "LOW"] as RiskLevel[]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" title="From" />
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" title="To" />
            <span className="spacer" />
            <span className="tiny muted">{filtered.length} events</span>
          </div>

          <AsyncSection
            state={incidents}
            loadingLabel="Loading incident record…"
            emptyTitle="No incidents recorded in this scope"
            emptyHint="Historical records are ingested from GSI Bhukosh and NASA COOLR exports."
            isEmpty={() => (incidents.data ?? []).length === 0}
            rows={6}
          >
            {() =>
              filtered.length === 0 ? (
                <div className="card-body">
                  <EmptyState title="No incidents match these filters" hint="Widen the date range or clear the search." />
                </div>
              ) : view === "TABLE" ? (
                <div className="table-wrap">
                  <table className="data" style={{ minWidth: 940 }}>
                    <thead>
                      <tr>
                        {th("date", "Date")}
                        <th scope="col">Location</th>
                        <th scope="col">Type</th>
                        {th("severity", "Severity")}
                        <th scope="col">Rainfall 24h</th>
                        {th("riskScoreAtEvent", "Risk score")}
                        <th scope="col">Affected road</th>
                        {th("affectedPopulation", "Population")}
                        {th("responseTimeMinutes", "Response")}
                        <th scope="col">Pre-alerted</th>
                        <th scope="col">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((i) => (
                        <tr key={i.id}>
                          <td className="mono">{formatDate(i.date)}</td>
                          <td>
                            {i.location}
                            <div className="tiny muted">{i.district}</div>
                          </td>
                          <td>{titleCase(i.incidentType)}</td>
                          <td>
                            <RiskBadge level={i.severity} />
                          </td>
                          <td className="mono">{i.rainfall24h} mm</td>
                          <td className="mono">{i.riskScoreAtEvent}</td>
                          <td>{i.affectedRoad}</td>
                          <td className="mono">{i.affectedPopulation.toLocaleString("en-IN")}</td>
                          <td className="mono">{i.responseTimeMinutes} min</td>
                          <td style={{ color: i.predicted ? "var(--low)" : "var(--sev)", fontWeight: 600 }}>
                            {i.predicted ? "Yes" : "No"}
                          </td>
                          <td className="tiny">{titleCase(i.status)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : view === "TIMELINE" ? (
                <div className="card-body">
                  <IncidentTimeline incidents={filtered.slice(0, 25)} />
                </div>
              ) : (
                <AsyncSection state={zones} loadingLabel="Loading map…">
                  {(z) => (
                    <RiskMap
                      zones={z}
                      incidents={filtered}
                      activeLayers={new Set(["incidents", "risk_heatmap"])}
                      height={480}
                    />
                  )}
                </AsyncSection>
              )
            }
          </AsyncSection>
        </section>
      </div>
    </>
  );
}

function IncidentTimeline({ incidents }: { incidents: HistoricalIncident[] }) {
  return (
    <div className="tl">
      {incidents.map((i) => (
        <div className="tl-item" key={i.id}>
          <span
            className="tl-dot"
            style={{
              background:
                i.severity === "CRITICAL"
                  ? "var(--sev)"
                  : i.severity === "HIGH"
                    ? "var(--high)"
                    : i.severity === "MODERATE"
                      ? "var(--mod)"
                      : "var(--low)",
            }}
          />
          <div className="tl-date">
            {formatDate(i.date)} · {i.district}
          </div>
          <h4>
            {titleCase(i.incidentType)} — {i.location}
          </h4>
          <p>
            {i.rainfall24h} mm in 24 h, risk score {i.riskScoreAtEvent} at the time.{" "}
            {i.affectedRoad} affected, {i.affectedPopulation.toLocaleString("en-IN")} people. Response
            in {i.responseTimeMinutes} minutes.{" "}
            {i.predicted
              ? "An alert was already open before the event."
              : "No alert was open — added to the retraining set."}
          </p>
        </div>
      ))}
    </div>
  );
}
