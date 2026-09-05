import { useMemo, useState } from "react";
import type { Sensor, SensorStatus, SensorType } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { sensorService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, KpiCard } from "@/components/ui/primitives";
import { SensorDetailDrawer, SensorTable } from "@/components/sensors/SensorViews";
import { DonutChart } from "@/components/charts";
import { sensorTypeLabel } from "@/data/sensorTypes";
import { matchesQuery } from "@/utils";

const TYPES: SensorType[] = [
  "RAIN_GAUGE",
  "SOIL_MOISTURE",
  "PIEZOMETER",
  "TILTMETER",
  "EXTENSOMETER",
  "GEOPHONE",
  "WEATHER_STATION",
];

export function SensorNetwork() {
  const app = useApp();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<SensorStatus | "ALL">("ALL");
  const [type, setType] = useState<SensorType | "ALL">("ALL");
  const [issue, setIssue] = useState<"ALL" | "LOW_BATTERY" | "COMMS">("ALL");
  const [open, setOpen] = useState<Sensor | null>(null);

  const sensors = useAsync(() => sensorService.getSensors(app.scope), [app.stateCode, app.districtId]);
  const summary = useAsync(() => sensorService.getSensorSummary(app.scope), [app.stateCode, app.districtId]);

  const filtered = useMemo(() => {
    let list = sensors.data ?? [];
    if (status !== "ALL") list = list.filter((s) => s.status === status);
    if (type !== "ALL") list = list.filter((s) => s.type === type);
    if (issue === "LOW_BATTERY") list = list.filter((s) => s.batteryPct < 25);
    if (issue === "COMMS") list = list.filter((s) => s.rssiDbm < -105);
    if (query.trim()) list = list.filter((s) => matchesQuery(query, s.id, s.name, s.district, s.zoneId));
    return list;
  }, [sensors.data, status, type, issue, query]);

  return (
    <>
      <PageHeader
        title="Sensor Network"
        subtitle="Fleet health, reliability and the confidence each prediction inherits"
        updatedAt={sensors.fetchedAt}
        actions={
          <button className="btn sm" type="button" onClick={() => { sensors.reload(); summary.reload(); }}>
            Refresh fleet
          </button>
        }
      />

      <div className="stack">
        

        <AsyncSection state={summary} loadingLabel="Loading fleet summary…" rows={2}>
          {(s) => (
            <>
              <div className="grid grid-kpi">
                <KpiCard label="Total sensors" value={s.total} note="Deployed in scope" />
                <KpiCard label="Online" value={s.online} note={`${s.uptimePct}% of fleet`} level="LOW" />
                <KpiCard label="Degraded" value={s.degraded} level={s.degraded > 0 ? "MODERATE" : "LOW"} note="Reporting with reduced confidence" />
                <KpiCard label="Offline" value={s.offline} level={s.offline > 0 ? "HIGH" : "LOW"} note="No data reaching the risk engine" />
                <KpiCard label="Low battery" value={s.lowBattery} note="Below 25% — schedule replacement" />
                <KpiCard label="Communication failures" value={s.commFailures} note="Uplink below −105 dBm" />
                <KpiCard label="Mean health score" value={s.meanHealth} unit="/100" note="Weighted across five sub-scores" />
                <KpiCard
                  label="Prediction confidence"
                  value={s.total ? Math.round((s.online / s.total) * 100) : 0}
                  unit="%"
                  note="Share of zones with a fully reporting instrument set"
                />
              </div>

              <div className="grid grid-2 grid-1-mobile">
                <Card title="Fleet health" subtitle="Distribution by reporting status">
                  <DonutChart
                    title="Sensor fleet health distribution"
                    centerValue={`${s.uptimePct}%`}
                    centerLabel="uptime"
                    data={[
                      { label: "Online", value: s.online, color: "var(--low)" },
                      { label: "Degraded", value: s.degraded, color: "var(--mod)" },
                      { label: "Offline", value: s.offline, color: "var(--sev)" },
                    ]}
                  />
                </Card>

                <Card title="Why sensor health matters" subtitle="Risk confidence vs risk score">
                  <p style={{ fontSize: 13 }}>
                    A high risk score from a degraded instrument set is not the same warning as a high
                    score from a healthy one. The platform publishes both, so a duty officer can tell a
                    genuine escalation from a data-quality artefact before committing a response team.
                  </p>
                  <div className="grid grid-2" style={{ marginTop: 10, gap: 8 }}>
                    <div className="card soft" style={{ padding: "9px 11px" }}>
                      <div className="eyebrow">High risk · high confidence</div>
                      <div className="tiny">Act — dispatch and issue warnings.</div>
                    </div>
                    <div className="card soft" style={{ padding: "9px 11px" }}>
                      <div className="eyebrow">High risk · low confidence</div>
                      <div className="tiny">Verify — send a field team and restore the instruments.</div>
                    </div>
                  </div>
                  <div className="callout info" style={{ marginTop: 10 }}>
                    Health scoring weights: completeness 25%, validity 25%, stability 20%, noise 15%,
                    communications 15%.
                  </div>
                </Card>
              </div>
            </>
          )}
        </AsyncSection>

        <section className="card">
          <div className="toolbar">
            <input
              type="search"
              placeholder="Search by sensor ID, site or district…"
              aria-label="Search sensors"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ flex: "1 1 200px" }}
            />
            <select value={status} onChange={(e) => setStatus(e.target.value as SensorStatus | "ALL")} aria-label="Status">
              <option value="ALL">Any status</option>
              <option value="ONLINE">Online</option>
              <option value="DEGRADED">Degraded</option>
              <option value="OFFLINE">Offline</option>
            </select>
            <select value={type} onChange={(e) => setType(e.target.value as SensorType | "ALL")} aria-label="Sensor type">
              <option value="ALL">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {sensorTypeLabel(t)}
                </option>
              ))}
            </select>
            <select value={issue} onChange={(e) => setIssue(e.target.value as typeof issue)} aria-label="Known issues">
              <option value="ALL">All sensors</option>
              <option value="LOW_BATTERY">Low battery only</option>
              <option value="COMMS">Weak uplink only</option>
            </select>
            <span className="spacer" />
            <span className="tiny muted">{filtered.length} shown</span>
          </div>

          <AsyncSection
            state={sensors}
            loadingLabel="Waiting for sensor data…"
            emptyTitle="No sensors deployed in this scope"
            emptyHint="Select another district, or review the deployment plan in Reports & Analytics."
            isEmpty={() => (sensors.data ?? []).length === 0}
            rows={6}
          >
            {() =>
              filtered.length === 0 ? (
                <div className="card-body">
                  <EmptyState title="No sensors match these filters" hint="Try clearing the search or status filter." />
                </div>
              ) : (
                <SensorTable sensors={filtered} onOpen={setOpen} />
              )
            }
          </AsyncSection>
        </section>
      </div>

      <SensorDetailDrawer sensor={open} open={Boolean(open)} onClose={() => setOpen(null)} />
    </>
  );
}
