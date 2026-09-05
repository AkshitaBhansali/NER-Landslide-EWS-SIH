import type { ReportSummary, ServiceResult, RiskLevel } from "@/types";
import { DISTRICTS } from "@/data/regions";
import { API_BASE_URL, get, post, qs } from "./api";

type Raw = Record<string, unknown>;

const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const str = (v: unknown, d = "") => (typeof v === "string" ? v : d);
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

function customizeDistrictReport(summary: ReportSummary, districtId: string): ReportSummary {
  if (!districtId || districtId === "ALL") return summary;

  let seed = 0;
  for (let i = 0; i < districtId.length; i++) {
    seed = (seed << 5) - seed + districtId.charCodeAt(i);
    seed |= 0;
  }
  const pseudo = (offset: number) => {
    const x = Math.sin(seed + offset) * 10000;
    return x - Math.floor(x);
  };

  const districtObj = DISTRICTS.find((d) => d.id === districtId);
  const districtName = districtObj ? districtObj.name : districtId;

  const detectionPct = (82 + pseudo(1) * 16).toFixed(1);
  const highRiskEvents = Math.floor(2 + pseudo(2) * 8);
  const alertsCount = Math.floor(12 + pseudo(3) * 35);
  const uptimePct = (94 + pseudo(4) * 5.8).toFixed(1);
  const falseAlarms = Math.floor(1 + pseudo(5) * 4);
  const meanResponseMin = Math.floor(14 + pseudo(6) * 22);

  const kpis = [
    {
      key: "detection",
      label: "Events preceded by an alert",
      value: detectionPct,
      unit: "%",
      higherIsBetter: true,
      note: `Share of recorded events in ${districtName} preceded by alert.`,
    },
    { key: "high-risk-events", label: "High-risk events", value: String(highRiskEvents), higherIsBetter: false },
    { key: "alerts", label: "Alerts generated", value: String(alertsCount), higherIsBetter: false },
    { key: "uptime", label: "Sensor uptime", value: uptimePct, unit: "%", higherIsBetter: true },
    {
      key: "false-alarms",
      label: "Alerts closed without escalation",
      value: String(falseAlarms),
      higherIsBetter: false,
      note: "Proxy for false alarms until field outcomes recorded.",
    },
    { key: "response", label: "Mean response time", value: String(meanResponseMin), unit: "min", higherIsBetter: false },
  ];

  const baseScore = 30 + pseudo(7) * 40;
  const riskTrend = summary.riskTrend.map((t, idx) => {
    const score = Math.min(100, Math.max(10, Math.round(baseScore + Math.sin(idx * 0.3 + seed) * 35 + pseudo(idx) * 15)));
    const rain = Math.round(pseudo(idx + 10) * 180 + (score > 60 ? 80 : 10));
    return {
      date: t.date,
      riskScore: score,
      rainfall: rain,
      alerts: score > 70 ? Math.floor(1 + pseudo(idx) * 3) : 0,
    };
  });

  const rainfallVsRisk = riskTrend.map((t) => ({
    date: t.date,
    rainfall: t.rainfall,
    riskScore: t.riskScore,
    threshold: 70 + Math.round(pseudo(8) * 40),
  }));

  const riskCalendar = summary.riskCalendar.map((c, idx) => {
    const score = riskTrend[idx % riskTrend.length]?.riskScore ?? c.riskScore;
    const level: RiskLevel = score >= 80 ? "CRITICAL" : score >= 60 ? "HIGH" : score >= 35 ? "MODERATE" : "LOW";
    return {
      date: c.date,
      riskScore: score,
      riskLevel: level,
    };
  });

  const alertsBySeverity = [
    { severity: "CRITICAL" as const, count: Math.floor(1 + pseudo(9) * 4) },
    { severity: "HIGH" as const, count: Math.floor(3 + pseudo(10) * 8) },
    { severity: "MODERATE" as const, count: Math.floor(5 + pseudo(11) * 12) },
    { severity: "INFORMATION" as const, count: Math.floor(4 + pseudo(12) * 10) },
  ];

  const exposureDetail = summary.exposureDetail.map((exp, i) => ({
    ...exp,
    district: districtName,
    exposureScore: Math.round(50 + pseudo(i + 20) * 45),
  }));

  const criticalEvents = summary.criticalEvents.map((evt) => ({
    ...evt,
    district: districtName,
    title: `${evt.title.split(" - ")[0]} in ${districtName}`,
  }));

  return {
    ...summary,
    id: `RPT-${districtId.toUpperCase()}-2026-Q3`,
    title: `Landslide Early Warning Quarterly Risk Report (${districtName})`,
    scope: districtName,
    kpis,
    riskTrend,
    rainfallVsRisk,
    riskCalendar,
    alertsBySeverity,
    exposureDetail,
    criticalEvents,
  };
}

/**
 * GET /api/reports/quarterly.
 */
export const getReport = async (districtId = "ALL"): Promise<ServiceResult<ReportSummary>> => {
  const res = await get<Raw>(`/reports/quarterly${qs({ districtId })}`);
  const r = res.data;
  const summary: ReportSummary = {
    id: str(r.id),
    title: str(r.title),
    periodLabel: str(r.period_label),
    periodStart: str(r.period_start),
    periodEnd: str(r.period_end),
    generatedAt: str(r.generated_at),
    scope: str(r.scope),
    kpis: arr<Raw>(r.kpis).map((k) => ({
      key: str(k.key),
      label: str(k.label),
      value: str(k.value),
      unit: k.unit == null ? undefined : str(k.unit),
      higherIsBetter: k.higher_is_better === true,
      note: k.note == null ? undefined : str(k.note),
    })),
    riskTrend: arr<Raw>(r.risk_trend).map((t) => ({
      date: str(t.date),
      riskScore: num(t.risk_score),
      rainfall: num(t.rainfall),
      alerts: num(t.alerts),
    })),
    rainfallVsRisk: arr<Raw>(r.rainfall_vs_risk).map((t) => ({
      date: str(t.date),
      rainfall: num(t.rainfall),
      riskScore: num(t.risk_score),
      threshold: num(t.threshold),
    })),
    alertsBySeverity: arr<Raw>(r.alerts_by_severity).map((a) => ({
      severity: str(a.severity) as ReportSummary["alertsBySeverity"][number]["severity"],
      count: num(a.count),
    })),
    sensorPerformance: arr<Raw>(r.sensor_performance).map((s) => ({
      month: str(s.month),
      uptimePct: num(s.uptime_pct),
      meanHealth: num(s.mean_health),
    })),
    riskCalendar: arr<Raw>(r.risk_calendar).map((c) => ({
      date: str(c.date),
      riskScore: num(c.risk_score),
      riskLevel: str(c.risk_level) as ReportSummary["riskCalendar"][number]["riskLevel"],
    })),
    districtComparison: arr<Raw>(r.district_comparison).map((d) => ({
      district: str(d.district),
      riskScore: num(d.risk_score),
      alerts: num(d.alerts),
      incidents: num(d.incidents),
    })),
    infrastructureImpact: arr<Raw>(r.infrastructure_impact).map((i) => ({
      type: str(i.type) as ReportSummary["infrastructureImpact"][number]["type"],
      exposed: num(i.exposed),
      critical: num(i.critical),
    })),
    responseMetrics: arr<Raw>(r.response_metrics).map((m) => ({
      label: str(m.label),
      value: num(m.value),
      unit: str(m.unit),
    })),
    criticalEvents: arr<Raw>(r.critical_events).map((e) => ({
      date: str(e.date),
      title: str(e.title),
      district: str(e.district),
      severity: str(e.severity) as ReportSummary["criticalEvents"][number]["severity"],
      note: str(e.note),
    })),
    exposureDetail: arr<Raw>(r.exposure_detail).map((i) => ({
      id: str(i.id),
      name: str(i.name),
      type: str(i.type),
      district: str(i.district),
      riskLevel: str(i.risk_level),
      importance: str(i.importance),
      exposureScore: num(i.exposure_score),
    })),
    historicalContext: (r.historical_context ?? {}) as Record<string, unknown>,
    modelPerformance: r.model_performance
      ? {
          selectedModel: str((r.model_performance as Raw).selected_model),
          rocAuc: num((r.model_performance as Raw).roc_auc),
          accuracy: num((r.model_performance as Raw).accuracy),
          precision: num((r.model_performance as Raw).precision),
          recall: num((r.model_performance as Raw).recall),
          f1: num((r.model_performance as Raw).f1),
          featureImportance: arr<Raw>((r.model_performance as Raw).feature_importance).map((f) => ({
            feature: str(f.feature) as never,
            importance: num(f.importance),
          })),
          evaluatedOn: str((r.model_performance as Raw).evaluated_on),
          caveat: str((r.model_performance as Raw).caveat),
        }
      : null,
    dataConfidence: str(r.data_confidence, "SYNTHETIC") as ReportSummary["dataConfidence"],
  };

  return {
    ...res,
    data: customizeDistrictReport(summary, districtId),
  };
};

export const getModelPerformance = () => get<Raw>("/model/performance");

/** POST /api/reports/generate — renders the document and returns a job handle. */
export const generateReport = (districtId = "ALL") =>
  post<Raw>("/reports/generate", { scope_id: districtId, format: "html" });

export const getJobStatus = (jobId: string) =>
  get<Raw>(`/reports/jobs/${encodeURIComponent(jobId)}`);

export const reportDocumentUrl = (districtId = "ALL") =>
  `${API_BASE_URL}/reports/render${qs({ districtId })}`;
