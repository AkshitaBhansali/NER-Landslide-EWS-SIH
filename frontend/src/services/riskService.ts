import type { RiskSummary, RiskTrendPoint, RiskZone, ServiceResult } from "@/types";
import * as A from "./adapters";
import { get, qs, type ScopeFilter } from "./api";

type Raw = Record<string, unknown>;

/** GET /api/risk/zones — sorted worst first by the server. */
export const getRiskZones = async (scope: ScopeFilter = {}): Promise<ServiceResult<RiskZone[]>> => {
  const res = await get<Raw[]>(`/risk/zones${qs(scope)}`);
  return { ...res, data: res.data.map(A.adaptRiskZone) };
};

/** GET /api/risk/zones/:id */
export const getRiskZoneById = async (id: string): Promise<ServiceResult<RiskZone>> => {
  const res = await get<Raw>(`/risk/zones/${encodeURIComponent(id)}`);
  return { ...res, data: A.adaptRiskZone(res.data) };
};

/** GET /api/risk/zones/:id/explain — the LSI/TI breakdown behind the score. */
export const explainRiskZone = (id: string) =>
  get<Raw>(`/risk/zones/${encodeURIComponent(id)}/explain`);

/** GET /api/risk/summary */
export const getRiskSummary = async (
  scope: ScopeFilter = {},
): Promise<ServiceResult<RiskSummary>> => {
  const res = await get<Raw>(`/risk/summary${qs(scope)}`);
  return { ...res, data: A.adaptRiskSummary(res.data) as RiskSummary };
};

/** GET /api/risk/trend */
export const getRiskTrend = async (
  districtId: string,
  days = 30,
): Promise<ServiceResult<RiskTrendPoint[]>> => {
  const res = await get<Raw[]>(`/risk/trend${qs({ districtId }, { days })}`);
  return { ...res, data: res.data.map(A.adaptTrendPoint) };
};

/** GET /api/risk/pipeline — the sensors -> risk -> alerts strip on the Overview. */
export const getPipelineHealth = async (scope: ScopeFilter = {}) => {
  const res = await get<Raw>(`/risk/pipeline${qs(scope)}`);
  return { ...res, data: A.adaptPipeline(res.data) };
};
