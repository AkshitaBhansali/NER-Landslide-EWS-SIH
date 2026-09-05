import { useMemo, useState } from "react";
import type { Sensor, SensorStatus } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { riskService, sensorService, weatherService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, KpiCard, RiskBadge, StatusIndicator } from "@/components/ui/primitives";
import { SensorCard, SensorDetailDrawer } from "@/components/sensors/SensorViews";
import { WeatherPanel } from "@/components/weather/WeatherPanel";
import { LineChart } from "@/components/charts";
import { riskVar } from "@/utils";

const STATUS_FILTERS: (SensorStatus | "ALL")[] = ["ALL", "ONLINE", "DEGRADED", "OFFLINE"];

/**
 * "What is happening right now" at instrument level. The Overview answers *where*;
 * this page answers *what the ground is doing*.
 */
export function LiveMonitoring() {
  const app = useApp();
  const [statusFilter, setStatusFilter] = useState<SensorStatus | "ALL">("ALL");
  const [openSensor, setOpenSensor] = useState<Sensor | null>(null);

  const summary = useAsync(() => riskService.getRiskSummary(app.scope), [app.stateCode, app.districtId]);
  const zones = useAsync(() => riskService.getRiskZones(app.scope), [app.stateCode, app.districtId]);
  const sensors = useAsync(() => sensorService.getSensors(app.scope), [app.stateCode, app.districtId]);
  const weather = useAsync(() => weatherService.getWeather(app.scope), [app.districtId]);
  const trend = useAsync(() => riskService.getRiskTrend(app.districtId, 14), [app.districtId]);

  const filtered = useMemo(
    () => (sensors.data ?? []).filter((s) => statusFilter === "ALL" || s.status === statusFilter),
    [sensors.data, statusFilter],
  );

  // Live environmental conditions are aggregated from the zones in scope, which is how
  // the risk engine consumes them too.
  const conditions = useMemo(() => {
    const z = zones.data ?? [];
    if (!z.length) return null;
    const avg = (f: (x: (typeof z)[number]) => number) => z.reduce((a, x) => a + f(x), 0) / z.length;
    const s = sensors.data ?? [];
    const byType = (t: Sensor["type"]) => s.filter((x) => x.type === t && x.status !== "OFFLINE");
    const meanOf = (t: Sensor["type"]) => {
      const list = byType(t);
      return list.length ? list.reduce((a, x) => a + x.reading, 0) / list.length : null;
    };
    return {
      rainfallNow: weather.data?.rainfallNow ?? 0,
      rainfall24h: avg((x) => x.rainfall24h),
      rainfall7d: avg((x) => x.rainfall7d),
      soilMoisture: avg((x) => x.soilMoisture),
      porePressure: meanOf("PIEZOMETER"),
      tilt: meanOf("TILTMETER"),
      movement: meanOf("EXTENSOMETER"),
      temperature: weather.data?.temperature ?? null,
    };
  }, [zones.data, sensors.data, weather.data]);

  return (
    <>
      <PageHeader
        title="Live Monitoring"
        subtitle="Environmental conditions and instrument readings feeding the risk engine"
        updatedAt={summary.data?.updatedAt}
        actions={
          <button className="btn sm" type="button" onClick={() => { sensors.reload(); zones.reload(); }}>
            Refresh readings
          </button>
        }
      />

      <div className="stack">
        {/* A. regional risk status */}
        <AsyncSection state={summary} loadingLabel="Loading regional status…" rows={2}>
          {(s) => (
            <section className="card pad">
              <div className="row between" style={{ alignItems: "flex-start" }}>
                <div>
                  <div className="eyebrow">Regional risk status</div>
                  <div className="row" style={{ gap: 12, marginTop: 4 }}>
                    <span
                      className="mono"
                      style={{ fontSize: 40, fontWeight: 600, lineHeight: 1, color: riskVar(s.regionalRiskLevel) }}
                    >
                      {s.regionalRiskScore}
                    </span>
                    <span>
                      <RiskBadge level={s.regionalRiskLevel} />
                      <div className="tiny muted" style={{ marginTop: 4 }}>
                        {app.scopeLabel} · {s.totalZones} zones · {s.highRiskZones} above the high-risk cut-off
                      </div>
                    </span>
                  </div>
                </div>
                <div className="row" style={{ gap: 16 }}>
                  <StatusIndicator status="ONLINE" label={`${s.sensorsOnline} online`} pulse />
                  <StatusIndicator status="DEGRADED" label={`${s.sensorsDegraded} degraded`} />
                  <StatusIndicator status="OFFLINE" label={`${s.sensorsOffline} offline`} />
                </div>
              </div>
            </section>
          )}
        </AsyncSection>

        {/* B. live environmental conditions */}
        <Card
          title="Live environmental conditions"
          subtitle="Aggregated across the zones in scope"
        >
          {conditions ? (
            <div className="grid grid-4">
              <KpiCard label="Rainfall now" value={conditions.rainfallNow.toFixed(1)} unit=" mm/h" />
              <KpiCard label="Cumulative 24h" value={conditions.rainfall24h.toFixed(0)} unit=" mm" />
              <KpiCard label="Cumulative 7d" value={conditions.rainfall7d.toFixed(0)} unit=" mm" />
              <KpiCard label="Soil moisture" value={conditions.soilMoisture.toFixed(1)} unit="% VWC" />
              <KpiCard
                label="Pore-water pressure"
                value={conditions.porePressure !== null ? conditions.porePressure.toFixed(1) : "—"}
                unit=" kPa"
                note={conditions.porePressure === null ? "No piezometer reporting" : undefined}
              />
              <KpiCard
                label="Slope movement"
                value={conditions.movement !== null ? conditions.movement.toFixed(1) : "—"}
                unit=" mm"
                note={conditions.movement === null ? "No extensometer reporting" : undefined}
              />
              <KpiCard
                label="Tilt / inclination"
                value={conditions.tilt !== null ? conditions.tilt.toFixed(2) : "—"}
                unit="°"
                note={conditions.tilt === null ? "No tiltmeter reporting" : undefined}
              />
              <KpiCard
                label="Temperature"
                value={conditions.temperature !== null ? conditions.temperature.toFixed(1) : "—"}
                unit="°C"
              />
            </div>
          ) : (
            <div className="state-block">
              <strong>Waiting for sensor data…</strong>
              <span>No zones are reporting in the selected scope.</span>
            </div>
          )}
        </Card>

        <div className="grid grid-2 grid-1-mobile">
          <Card title="Risk vs rainfall" subtitle="Last 14 days in scope">
            <AsyncSection state={trend} loadingLabel="Loading series…" isEmpty={(t) => t.length === 0}>
              {(t) => (
                <LineChart
                  title="Risk score against rainfall over the last 14 days"
                  labels={t.map((p) => new Date(p.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }))}
                  series={[
                    { label: "Rainfall (mm)", color: "var(--info)", values: t.map((p) => p.rainfall), fill: true },
                    { label: "Risk score", color: "var(--high)", values: t.map((p) => p.riskScore) },
                  ]}
                  yMax={200}
                  threshold={{ value: 95, label: "Alert threshold" }}
                />
              )}
            </AsyncSection>
          </Card>

          <Card title="Weather" subtitle="Current conditions and 5-day outlook">
            <AsyncSection state={weather} loadingLabel="Fetching weather…">
              {(w) => <WeatherPanel weather={w} />}
            </AsyncSection>
          </Card>
        </div>

        {/* C. sensor network */}
        <Card
          title="Sensor network"
          subtitle={`${filtered.length} instruments shown`}
          actions={
            <div className="segmented">
              {STATUS_FILTERS.map((s) => (
                <button key={s} type="button" aria-pressed={statusFilter === s} onClick={() => setStatusFilter(s)}>
                  {s === "ALL" ? "All" : s}
                </button>
              ))}
            </div>
          }
        >
          <AsyncSection
            state={sensors}
            loadingLabel="Waiting for sensor data…"
            emptyTitle="No sensors deployed in this scope"
            emptyHint="Select a different district, or expand the deployment plan."
            isEmpty={() => filtered.length === 0}
            rows={4}
          >
            {() => (
              <div className="grid grid-4">
                {filtered.slice(0, 16).map((s) => (
                  <SensorCard key={s.id} sensor={s} onOpen={setOpenSensor} />
                ))}
              </div>
            )}
          </AsyncSection>
          {filtered.length > 16 && (
            <div className="tiny muted" style={{ marginTop: 10 }}>
              Showing 16 of {filtered.length}. The full fleet with search and sorting is on the Sensor
              Network page.
            </div>
          )}
        </Card>
      </div>

      <SensorDetailDrawer sensor={openSensor} open={Boolean(openSensor)} onClose={() => setOpenSensor(null)} />
    </>
  );
}
