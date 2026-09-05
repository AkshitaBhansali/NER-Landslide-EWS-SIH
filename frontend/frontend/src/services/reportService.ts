import type { ReportSummary, ServiceResult } from "@/types";
import { API_BASE_URL, get, post, qs } from "./api";

type Raw = Record<string, unknown>;

const num = (v: unknown, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const str = (v: unknown, d = "") => (typeof v === "string" ? v : d);
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/**
 * GET /api/reports/quarterly.
 *
 * One request returns the whole report. That is deliberate on the server side: the
 * report is a single publication with internally consistent figures, and assembling
 * it from eight independent calls is how a KPI grid ends up disagreeing with the
 * chart printed below it.
 */
export const getReport = async (districtId = "ALL"): Promise<ServiceResult<ReportSummary>> => {
  const res = await get<Raw>(`/reports/quarterly${qs({ districtId })}`);
  const r = res.data;
  return {
    ...res,
    data: {
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
        date: str(t.date), riskScore: num(t.risk_score),
        rainfall: num(t.rainfall), alerts: num(t.alerts),
      })),
      rainfallVsRisk: arr<Raw>(r.rainfall_vs_risk).map((t) => ({
        date: str(t.date), rainfall: num(t.rainfall),
        riskScore: num(t.risk_score), threshold: num(t.threshold),
      })),
      alertsBySeverity: arr<Raw>(r.alerts_by_severity).map((a) => ({
        severity: str(a.severity) as ReportSummary["alertsBySeverity"][number]["severity"],
        count: num(a.count),
      })),
      sensorPerformance: arr<Raw>(r.sensor_performance).map((s) => ({
        month: str(s.month), uptimePct: num(s.uptime_pct), meanHealth: num(s.mean_health),
      })),
      riskCalendar: arr<Raw>(r.risk_calendar).map((c) => ({
        date: str(c.date), riskScore: num(c.risk_score),
        riskLevel: str(c.risk_level) as ReportSummary["riskCalendar"][number]["riskLevel"],
      })),
      districtComparison: arr<Raw>(r.district_comparison).map((d) => ({
        district: str(d.district), riskScore: num(d.risk_score),
        alerts: num(d.alerts), incidents: num(d.incidents),
      })),
      infrastructureImpact: arr<Raw>(r.infrastructure_impact).map((i) => ({
        type: str(i.type) as ReportSummary["infrastructureImpact"][number]["type"],
        exposed: num(i.exposed), critical: num(i.critical),
      })),
      responseMetrics: arr<Raw>(r.response_metrics).map((m) => ({
        label: str(m.label), value: num(m.value), unit: str(m.unit),
      })),
      criticalEvents: arr<Raw>(r.critical_events).map((e) => ({
        date: str(e.date), title: str(e.title), district: str(e.district),
        severity: str(e.severity) as ReportSummary["criticalEvents"][number]["severity"],
        note: str(e.note),
      })),
      exposureDetail: arr<Raw>(r.exposure_detail).map((i) => ({
        id: str(i.id), name: str(i.name), type: str(i.type),
        district: str(i.district), riskLevel: str(i.risk_level),
        importance: str(i.importance), exposureScore: num(i.exposure_score),
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
    },
  };
};

export const getModelPerformance = () => get<Raw>("/model/performance");

/** POST /api/reports/generate — renders the document and returns a job handle. */
export const generateReport = (districtId = "ALL") =>
  post<Raw>("/reports/generate", { scope_id: districtId, format: "html" });

export const getJobStatus = (jobId: string) =>
  get<Raw>(`/reports/jobs/${encodeURIComponent(jobId)}`);

/**
 * The printable document URL.
 *
 * Opened in a new tab rather than embedded: the report is designed for A4 print,
 * and the browser's own print-to-PDF typesets it better than any renderer we could
 * ship — and works with no network, no headless browser and no LaTeX installed.
 */
export const reportDocumentUrl = (districtId = "ALL") =>
  `${API_BASE_URL}/reports/render${qs({ districtId })}`;
