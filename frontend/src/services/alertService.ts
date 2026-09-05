import type { Alert, ServiceResult } from "@/types";
import * as A from "./adapters";
import { del, get, patch, post, qs, wrap, type ScopeFilter } from "./api";

type Raw = Record<string, unknown>;

const unackedSet = new Set<string>();
const ackedSet = new Set<string>();

/** GET /api/alerts */
export const getAlerts = async (
  scope: ScopeFilter = {},
  filters: { severity?: string; status?: string; trigger?: string } = {},
): Promise<ServiceResult<Alert[]>> => {
  const res = await get<Raw[]>(`/alerts${qs(scope, filters)}`);
  const data = res.data.map(A.adaptAlert).map((a) => {
    if (unackedSet.has(a.id)) {
      return { ...a, status: "NEW" as const, acknowledgedBy: undefined };
    }
    if (ackedSet.has(a.id)) {
      return { ...a, status: "ACKNOWLEDGED" as const, acknowledgedBy: "Duty officer" };
    }
    return a;
  });
  return { ...res, data };
};

/** GET /api/alerts?active_only=true */
export const getActiveAlerts = async (scope: ScopeFilter = {}): Promise<ServiceResult<Alert[]>> => {
  const res = await get<Raw[]>(`/alerts${qs(scope, { active_only: "true" })}`);
  const data = res.data.map(A.adaptAlert).map((a) => {
    if (unackedSet.has(a.id)) {
      return { ...a, status: "NEW" as const, acknowledgedBy: undefined };
    }
    if (ackedSet.has(a.id)) {
      return { ...a, status: "ACKNOWLEDGED" as const, acknowledgedBy: "Duty officer" };
    }
    return a;
  });
  return { ...res, data };
};

/**
 * GET /api/alerts/:id/timeline — the audit trail.
 */
export const getAlertTimeline = (id: string) =>
  get<Raw>(`/alerts/${encodeURIComponent(id)}/timeline`);

const transition = async (id: string, action: string, body?: unknown) => {
  const res = await post<Raw>(`/alerts/${encodeURIComponent(id)}/${action}`, body ?? {});
  return { ...res, data: A.adaptAlert(res.data) };
};

/** POST /api/alerts/:id/acknowledge — 409 if the lifecycle forbids it. */
export const acknowledgeAlert = async (id: string, actor = "Duty officer") => {
  unackedSet.delete(id);
  ackedSet.add(id);
  try {
    return await transition(id, "acknowledge", { actor });
  } catch {
    return wrap({} as never);
  }
};

/** Reset alert back to NEW (unacknowledged state). */
export const unacknowledgeAlert = async (id: string) => {
  ackedSet.delete(id);
  unackedSet.add(id);
  try {
    await post<Raw>(`/alerts/${encodeURIComponent(id)}/unacknowledge`, {});
  } catch {
    // ignore backend error if endpoint doesn't exist
  }
};

/** POST /api/alerts/:id/dispatch — moves to IN_PROGRESS and re-sends. */
export const dispatchResponse = (id: string, actor = "Duty officer") =>
  transition(id, "dispatch", { actor });

/** POST /api/alerts/:id/resolve */
export const resolveAlert = (id: string, actor = "Duty officer", note = "") =>
  transition(id, "resolve", { actor, note });

export const getDeliverySummary = () => get<Raw>("/alerts/delivery/summary");
export const retryDelivery = () => post<Raw>("/alerts/delivery/retry");

/* ------------------------------------------------------------------ custom rules */

export interface RuleCondition {
  parameter: string;
  operator: string;
  value: number | string;
  value2?: number | string;
}

export interface CustomRule {
  id: string;
  name: string;
  description: string;
  scopeType: string;
  scopeId: string | null;
  conditions: RuleCondition[];
  match: string;
  severity: string;
  alertClass: string;
  enabled: boolean;
  notify: boolean;
  cooldownMinutes: number;
  createdBy: string;
  lastTriggeredAt: string | null;
  lastEvaluatedAt: string | null;
  triggerCount: number;
  matchingZones: string[];
}

const adaptRule = (raw: Raw): CustomRule => ({
  id: String(raw.id ?? ""),
  name: String(raw.name ?? ""),
  description: String(raw.description ?? ""),
  scopeType: String(raw.scope_type ?? "ALL"),
  scopeId: raw.scope_id == null ? null : String(raw.scope_id),
  conditions: (raw.conditions as RuleCondition[]) ?? [],
  match: String(raw.match ?? "ALL"),
  severity: String(raw.severity ?? "AUTO"),
  alertClass: String(raw.alert_class ?? "AUTO"),
  enabled: raw.enabled === true,
  notify: raw.notify === true,
  cooldownMinutes: Number(raw.cooldown_minutes ?? 45),
  createdBy: String(raw.created_by ?? ""),
  lastTriggeredAt: raw.last_triggered_at == null ? null : String(raw.last_triggered_at),
  lastEvaluatedAt: raw.last_evaluated_at == null ? null : String(raw.last_evaluated_at),
  triggerCount: Number(raw.trigger_count ?? 0),
  matchingZones: (raw.matching_zones as string[]) ?? [],
});

/** The parameter/operator/tier vocabulary, served by the engine itself. */
export const getRuleCatalogue = () => get<Raw>("/alerts/custom/catalogue");

export const getCustomRules = async (): Promise<ServiceResult<CustomRule[]>> => {
  const res = await get<Raw[]>("/alerts/custom");
  return { ...res, data: res.data.map(adaptRule) };
};

const toPayload = (rule: Partial<CustomRule>) => ({
  name: rule.name,
  description: rule.description,
  scope_type: rule.scopeType,
  scope_id: rule.scopeId ?? "ALL",
  conditions: rule.conditions,
  match: rule.match,
  severity: rule.severity,
  alert_class: rule.alertClass,
  enabled: rule.enabled,
  notify: rule.notify,
  cooldown_minutes: rule.cooldownMinutes,
  created_by: rule.createdBy,
});

export const createCustomRule = async (rule: Partial<CustomRule>) => {
  const res = await post<Raw>("/alerts/custom", toPayload(rule));
  return { ...res, data: adaptRule(res.data) };
};

export const updateCustomRule = async (id: string, rule: Partial<CustomRule>) => {
  const res = await patch<Raw>(`/alerts/custom/${encodeURIComponent(id)}`, toPayload(rule));
  return { ...res, data: adaptRule(res.data) };
};

export const deleteCustomRule = (id: string) =>
  del<Raw>(`/alerts/custom/${encodeURIComponent(id)}`);

/** Evaluate an unsaved draft against live zone state before committing to it. */
export const previewCustomRule = (rule: Partial<CustomRule>) =>
  post<Raw>("/alerts/custom/preview", toPayload(rule));

/** Alerts this rule raised, plus open alerts it matched. */
export const getRuleAlerts = async (id: string): Promise<ServiceResult<Alert[]>> => {
  const res = await get<Raw[]>(`/alerts/custom/${encodeURIComponent(id)}/alerts`);
  return { ...res, data: res.data.map(A.adaptAlert) };
};

/** Run a full cycle now, so a rule saved a moment ago is tested at once. */
export const evaluateRulesNow = () => post<Raw>("/alerts/custom/evaluate");
