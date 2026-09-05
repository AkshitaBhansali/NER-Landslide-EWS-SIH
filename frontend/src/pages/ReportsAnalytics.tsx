import { useState } from "react";
import type { AlertSeverity, RiskLevel } from "@/types";
import { useApp, districtsInScope } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { gisService, reportService, riskService, sensorService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, RiskBadge } from "@/components/ui/primitives";
import { BarChart, DonutChart, HBarChart, LineChart, RiskCalendar } from "@/components/charts";
import { RiskMap } from "@/components/map/RiskMap";
import { titleCase } from "@/utils";

const SEVERITY_COLOR: Record<AlertSeverity, string> = {
  CRITICAL: "var(--sev)",
  HIGH: "var(--high)",
  MODERATE: "var(--mod)",
  INFORMATION: "var(--ink-3)",
};

type Period = "30" | "90";

export function ReportsAnalytics() {
  const app = useApp();
  const districts = districtsInScope(app.stateCode);
  const [area, setArea] = useState<string>(app.districtId);
  const [period, setPeriod] = useState<Period>("90");
  const [riskFilter, setRiskFilter] = useState<RiskLevel | "ALL">("ALL");
  const [generating, setGenerating] = useState(false);

  const report = useAsync(() => reportService.getReport(area), [area]);

  const scopeFilter = { stateCode: app.stateCode, districtId: area };
  const zones = useAsync(() => riskService.getRiskZones(scopeFilter), [app.stateCode, area]);
  const sensors = useAsync(() => sensorService.getSensors(scopeFilter), [app.stateCode, area]);
  const roads = useAsync(() => gisService.getRoads(scopeFilter), [app.stateCode, area]);

  const generate = async () => {
    setGenerating(true);
    try {
      await reportService.generateReport(area);
      await report.reload();
      zones.reload();
      app.toast({
        tone: "success",
        title: "Report generated",
        body: `Analytics and report summary updated for ${areaLabel}.`,
      });
    } catch (err) {
      app.toast({
        tone: "error",
        title: "Report generation failed",
        body: err instanceof Error ? err.message : "The reporting service did not respond.",
      });
    } finally {
      setGenerating(false);
    }
  };

  const areaLabel =
    area === "ALL"
      ? "North Eastern Region: all districts"
      : districts.find((d) => d.id === area)?.name ?? area;

  return (
    <>
      <PageHeader
        title="Reports & analytics"
        subtitle={`What happened over the period, and what the instruments recorded: ${areaLabel}`}
      />

      <div className="stack">
        <Card title="Report scope" subtitle="Select an area and period to update the analytics report">
          <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label className="field">
              <span>Area</span>
              <select value={area} onChange={(e) => setArea(e.target.value)}>
                <option value="ALL">All districts in scope</option>
                {districts.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Period</span>
              <select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
              </select>
            </label>
            <label className="field">
              <span>Risk band</span>
              <select
                value={riskFilter}
                onChange={(e) => setRiskFilter(e.target.value as RiskLevel | "ALL")}
              >
                <option value="ALL">All bands</option>
                {(["CRITICAL", "HIGH", "MODERATE", "LOW"] as const).map((l) => (
                  <option key={l} value={l}>{titleCase(l)}</option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn primary"
              onClick={generate}
              disabled={generating}
            >
              {generating ? "Generating…" : "Generate report"}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => window.open(reportService.reportDocumentUrl(area), "_blank", "noopener")}
              title="Open printable document / download PDF"
            >
              Download PDF
            </button>
          </div>
          <p className="tiny muted" style={{ marginTop: 10 }}>
            The document is generated from this area's own records: risk history,
            alerts, sensor performance, recorded events and exposure. Selecting a
            different district produces different figures throughout.
          </p>
        </Card>

        {/* District Risk Heatmap */}
        <Card title="District risk heatmap" subtitle={`Spatial risk distribution and monitoring coverage: ${areaLabel}`}>
          <AsyncSection state={zones} loadingLabel="Loading spatial heatmap…" rows={3}>
            {(z) => (
              <RiskMap
                zones={z}
                sensors={sensors.data ?? []}
                roads={roads.data ?? []}
                activeLayers={new Set(["risk_heatmap", "sensors", "roads"])}
                height={340}
                showStateLabels={false}
              />
            )}
          </AsyncSection>
        </Card>

        <AsyncSection state={report} loadingLabel="Compiling report…" rows={6}>
          {(r) => {
            const days = period === "30" ? 30 : 90;
            const trend = r.riskTrend.slice(-days);
            const rvr = r.rainfallVsRisk.slice(-days);
            const calendar =
              riskFilter === "ALL"
                ? r.riskCalendar.slice(-days)
                : r.riskCalendar.slice(-days).filter((c) => c.riskLevel === riskFilter);
            const peak = Math.max(0, ...trend.map((t) => t.riskScore));
            const alertTotal = r.alertsBySeverity.reduce((a, s) => a + s.count, 0);

            return (
              <>
                {/* KPIs */}
                <div className="kpi-row">
                  {r.kpis.map((k) => (
                    <div className="kpi" key={k.key} title={k.note}>
                      <div className="lab">{k.label}</div>
                      <div className="val">
                        {k.value}
                        {k.unit && <span className="unit">{k.unit}</span>}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="grid grid-2">
                  <Card
                    title="Risk trend"
                    subtitle="Did risk rise, and when: the shape of the period"
                  >
                    {trend.length === 0 ? (
                      <EmptyState
                        title="No scored days yet"
                        hint="The trend fills as the risk engine writes history. Run a sensor scenario to advance it."
                      />
                    ) : (
                      <LineChart
                        title="Mean risk score"
                        labels={trend.map((t) => t.date.slice(5, 10))}
                        series={[
                          { label: "Risk score", values: trend.map((t) => t.riskScore), color: "var(--geo)" },
                        ]}
                        yMax={100}
                        yLabel="score"
                      />
                    )}
                  </Card>

                  <Card
                    title="Rainfall against risk"
                    subtitle="Did risk follow the rain, and with what lag"
                  >
                    {rvr.length === 0 ? (
                      <EmptyState title="No rainfall history" hint="Nothing recorded for this period." />
                    ) : (
                      <LineChart
                        title="Rainfall and risk"
                        labels={rvr.map((t) => t.date.slice(5, 10))}
                        series={[
                          { label: "Rainfall (mm)", values: rvr.map((t) => t.rainfall), color: "#5d87a8" },
                          { label: "Risk score", values: rvr.map((t) => t.riskScore), color: "var(--geo)" },
                        ]}
                        threshold={{
                          value: rvr[0]?.threshold ?? 95,
                          label: "24h alert threshold",
                          color: "var(--sev)",
                        }}
                      />
                    )}
                  </Card>
                </div>

                <div className="grid grid-2">
                  <Card
                    title="Risk calendar"
                    subtitle={`Daily peak risk: peak ${Math.round(peak)} over the period`}
                  >
                    {calendar.length === 0 ? (
                      <EmptyState
                        title="No days in this risk band"
                        hint="Select a different risk band filter."
                      />
                    ) : (
                      <RiskCalendar days={calendar} />
                    )}
                  </Card>

                  <Card
                    title="Alert distribution"
                    subtitle={`${alertTotal} issued: how much of it was actionable`}
                  >
                    <DonutChart
                      title="Alert count by severity"
                      centerLabel="Total alerts"
                      centerValue={`${alertTotal}`}
                      data={r.alertsBySeverity.map((a) => ({
                        label: titleCase(a.severity),
                        value: a.count,
                        color: SEVERITY_COLOR[a.severity],
                      }))}
                    />
                  </Card>
                </div>

                <div className="grid grid-2">
                  <Card
                    title="Infrastructure exposure"
                    subtitle="Risk x importance: the inspection queue"
                  >
                    <HBarChart
                      data={r.infrastructureImpact.map((i) => ({
                        label: titleCase(i.type),
                        value: i.exposed,
                        color: "var(--high)",
                      }))}
                    />
                  </Card>

                  <Card title="Sensor fleet performance" subtitle="Monthly uptime and mean health">
                    <BarChart
                      title="Uptime percentage"
                      height={180}
                      data={r.sensorPerformance.map((s) => ({
                        label: s.month,
                        value: s.uptimePct,
                        color: "var(--geo)",
                      }))}
                    />
                  </Card>
                </div>

                {/* District Comparison */}
                <Card
                  title="District comparison"
                  subtitle="Ranked by mean risk score over the period"
                >
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th scope="col">District</th>
                          <th scope="col">Mean risk score</th>
                          <th scope="col">Alerts generated</th>
                          <th scope="col">Incidents recorded</th>
                        </tr>
                      </thead>
                      <tbody>
                        {r.districtComparison.map((d) => (
                          <tr key={d.district}>
                            <td>{d.district}</td>
                            <td className="mono">{d.riskScore}</td>
                            <td className="mono">{d.alerts}</td>
                            <td className="mono">{d.incidents}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>

                {/* Critical Events & Exposure Detail */}
                <div className="grid grid-2">
                  <Card title="Recorded critical events" subtitle="Events with alerts or retraining review">
                    <div className="stack" style={{ gap: 8 }}>
                      {r.criticalEvents.map((e, idx) => (
                        <div key={idx} style={{ borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
                          <div className="row between tiny">
                            <strong>{e.title}</strong>
                            <RiskBadge level={e.severity} />
                          </div>
                          <div className="tiny muted" style={{ marginTop: 2 }}>
                            {e.district} · {e.date.slice(0, 10)}
                          </div>
                          <div className="tiny" style={{ marginTop: 4 }}>
                            {e.note}
                          </div>
                        </div>
                      ))}
                    </div>
                  </Card>

                  <Card title="Top exposed assets" subtitle="Highest exposure score assets">
                    <div className="table-wrap">
                      <table className="data">
                        <thead>
                          <tr>
                            <th scope="col">Asset</th>
                            <th scope="col">Type</th>
                            <th scope="col">Risk level</th>
                            <th scope="col">Exposure score</th>
                          </tr>
                        </thead>
                        <tbody>
                          {r.exposureDetail.map((e) => (
                            <tr key={e.id}>
                              <td>{e.name}</td>
                              <td className="tiny">{titleCase(e.type)}</td>
                              <td>
                                <RiskBadge level={e.riskLevel as RiskLevel} />
                              </td>
                              <td className="mono">{e.exposureScore}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                </div>

                <div className="tiny muted" style={{ textAlign: "center", marginTop: 16 }}>
                  Data provenance: {r.dataConfidence}. Research prototype report generated for {areaLabel}.
                </div>
              </>
            );
          }}
        </AsyncSection>
      </div>
    </>
  );
}
