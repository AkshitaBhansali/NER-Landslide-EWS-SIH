import { useState } from "react";
import type { AlertSeverity, RiskLevel } from "@/types";
import { useApp, districtsInScope } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { reportService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, RiskBadge } from "@/components/ui/primitives";
import { BarChart, DonutChart, HBarChart, LineChart, RiskCalendar } from "@/components/charts";
import { titleCase } from "@/utils";

/**
 * Reports and analytics.
 *
 * The whole page is driven by one request. That is a server-side decision worth
 * respecting here: the report is a single publication with internally consistent
 * figures, and assembling it from eight independent calls is how a KPI grid ends up
 * disagreeing with the chart printed directly below it.
 *
 * Every chart on this page answers a question an emergency-management officer would
 * actually ask. Anything that was only decorative has been left out — a wall of
 * charts is not analysis, it is an invitation to stop looking.
 *
 * There is no recommendations section, on this page or in the generated document.
 * The report states what happened and what the instruments recorded; deciding what
 * to do about it is the district administration's job.
 */

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

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await reportService.generateReport(area);
      const url = String((res.data as Record<string, unknown>).view_url ?? "");
      app.toast({
        tone: "success",
        title: "Report generated",
        body: `${String((res.data as Record<string, unknown>).job_id)} · opening in a new tab.`,
      });
      // Opened rather than embedded: the document is laid out for A4, and the
      // browser's own print-to-PDF typesets it better than anything we could ship.
      window.open(reportService.reportDocumentUrl(area), "_blank", "noopener");
      if (!url) return;
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
      ? "North Eastern Region — all districts"
      : districts.find((d) => d.id === area)?.name ?? area;

  return (
    <>
      <PageHeader
        title="Reports & analytics"
        subtitle={`What happened over the period, and what the instruments recorded — ${areaLabel}`}
      />

      <div className="stack">
        <Card title="Report scope" subtitle="Select an area and period, then generate the document">
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
            <a
              className="btn"
              href={reportService.reportDocumentUrl(area)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open document
            </a>
          </div>
          <p className="tiny muted" style={{ marginTop: 10 }}>
            The document is generated from this area's own records — risk history,
            alerts, sensor performance, recorded events and exposure. Selecting a
            different district produces different figures throughout.
          </p>
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
            const hist = r.historicalContext as Record<string, unknown>;
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
                    subtitle="Did risk rise, and when — the shape of the period"
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
                    subtitle={`Daily peak risk · peak ${Math.round(peak)} over the period`}
                  >
                    {calendar.length === 0 ? (
                      <EmptyState
                        title="No days in this band"
                        hint="Clear the risk-band filter to see the full calendar."
                      />
                    ) : (
                      <RiskCalendar days={calendar} />
                    )}
                  </Card>

                  <Card
                    title="Alerts by severity"
                    subtitle={`${alertTotal} issued — how much of it was actionable`}
                  >
                    {alertTotal === 0 ? (
                      <EmptyState title="No alerts issued" hint="Nothing crossed a dispatch threshold in this period." />
                    ) : (
                      <DonutChart
                        title="Alerts by severity"
                        centerLabel="alerts"
                        centerValue={String(alertTotal)}
                        data={r.alertsBySeverity.map((s) => ({
                          label: titleCase(s.severity),
                          value: s.count,
                          color: SEVERITY_COLOR[s.severity],
                        }))}
                      />
                    )}
                  </Card>
                </div>

                <div className="grid grid-2">
                  <Card
                    title="Sensor performance"
                    subtitle="Could we see, and how well"
                  >
                    <BarChart
                      title="Fleet uptime (%)"
                      data={r.sensorPerformance.map((s) => ({
                        label: s.month,
                        value: s.uptimePct,
                        color: "var(--geo)",
                      }))}
                    />
                  </Card>

                  <Card
                    title="Infrastructure exposure"
                    subtitle="Risk × importance — the inspection queue"
                  >
                    {r.exposureDetail.length === 0 ? (
                      <EmptyState title="No assets in scope" hint="Select a district with mapped infrastructure." />
                    ) : (
                      <HBarChart
                        unit=" pts"
                        data={r.exposureDetail.slice(0, 8).map((i) => ({
                          label: i.name,
                          value: i.exposureScore,
                        }))}
                      />
                    )}
                  </Card>
                </div>

                {/* district comparison */}
                <Card
                  title="District comparison"
                  subtitle="Where the period concentrated"
                >
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th scope="col">District</th>
                          <th scope="col">Mean risk</th>
                          <th scope="col">Alerts</th>
                          <th scope="col">Recorded events</th>
                        </tr>
                      </thead>
                      <tbody>
                        {r.districtComparison.map((d) => (
                          <tr key={d.district}>
                            <td>{d.district}</td>
                            <td>
                              <RiskBadge
                                level={
                                  (d.riskScore >= 80
                                    ? "CRITICAL"
                                    : d.riskScore >= 60
                                      ? "HIGH"
                                      : d.riskScore >= 35
                                        ? "MODERATE"
                                        : "LOW") as RiskLevel
                                }
                              />{" "}
                              <span className="mono">{d.riskScore}</span>
                            </td>
                            <td className="mono">{d.alerts}</td>
                            <td className="mono">{d.incidents}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>

                {/* critical events */}
                <Card title="Critical events" subtitle="What actually happened, and whether it was warned">
                  {r.criticalEvents.length === 0 ? (
                    <EmptyState
                      title="No critical events in this period"
                      hint="Recorded high and critical severity events appear here with their warning status."
                    />
                  ) : (
                    <ul className="clean-list">
                      {r.criticalEvents.map((e) => (
                        <li key={`${e.date}-${e.title}`}>
                          <span>
                            <strong>{titleCase(e.title)}</strong>
                            <span className="tiny muted"> · {e.district}</span>
                            <div className="tiny muted">{e.note}</div>
                          </span>
                          <span className="tiny mono muted">{e.date.slice(0, 10)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                {/* historical context */}
                {hist?.available === true && (
                  <Card
                    title="Historical context"
                    subtitle={`Recorded regional events · ${String(hist.scope)} · ${String(hist.records)} records`}
                  >
                    <div className="kpi-row">
                      <div className="kpi">
                        <div className="lab">Recorded events</div>
                        <div className="val">{String(hist.events)}</div>
                      </div>
                      <div className="kpi">
                        <div className="lab">Occurrence rate</div>
                        <div className="val">
                          {String(hist.occurrence_rate_pct)}<span className="unit">%</span>
                        </div>
                      </div>
                      <div className="kpi">
                        <div className="lab">Mean 24h rain on event days</div>
                        <div className="val">
                          {String((hist.rainfall_on_event_days as Record<string, unknown>)?.mean_24h_mm ?? "—")}
                          <span className="unit">mm</span>
                        </div>
                      </div>
                      <div className="kpi">
                        <div className="lab">Mean 24h rain on quiet days</div>
                        <div className="val">
                          {String((hist.rainfall_on_quiet_days as Record<string, unknown>)?.mean_24h_mm ?? "—")}
                          <span className="unit">mm</span>
                        </div>
                      </div>
                    </div>
                    <p className="tiny muted" style={{ marginTop: 10 }}>
                      Reported at state resolution, which is the resolution the source
                      dataset has. The separation between event and quiet days is the
                      empirical basis for the combined rainfall-and-saturation rule.
                    </p>
                  </Card>
                )}

                {/* model performance */}
                {r.modelPerformance && (
                  <Card title="Model performance" subtitle="Held-out evaluation of the risk classifier">
                    <div className="kpi-row">
                      {[
                        ["ROC AUC", r.modelPerformance.rocAuc],
                        ["Accuracy", r.modelPerformance.accuracy],
                        ["Precision", r.modelPerformance.precision],
                        ["Recall", r.modelPerformance.recall],
                        ["F1", r.modelPerformance.f1],
                      ].map(([label, value]) => (
                        <div className="kpi" key={String(label)}>
                          <div className="lab">{String(label)}</div>
                          <div className="val">{Number(value).toFixed(3)}</div>
                        </div>
                      ))}
                    </div>
                    <div style={{ marginTop: 12 }}>
                      <p className="eyebrow">Feature importance</p>
                      <HBarChart
                        data={r.modelPerformance.featureImportance.slice(0, 6).map((f) => ({
                          label: String(f.feature),
                          value: Number(f.importance.toFixed(3)),
                        }))}
                      />
                    </div>
                    <p className="tiny muted" style={{ marginTop: 8 }}>
                      {r.modelPerformance.caveat}
                    </p>
                  </Card>
                )}

                <p className="tiny muted">
                  {r.scope} · {r.periodLabel} · generated {r.generatedAt.slice(0, 16).replace("T", " ")}.
                  Data provenance {r.dataConfidence}. Research prototype — not an official
                  publication.
                </p>
              </>
            );
          }}
        </AsyncSection>
      </div>
    </>
  );
}
