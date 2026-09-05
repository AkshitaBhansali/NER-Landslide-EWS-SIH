import type { HistoricalIncident, IncidentReport, ServiceResult } from "@/types";
import * as A from "./adapters";
import { get, patch, postForm, qs, type ScopeFilter } from "./api";

type Raw = Record<string, unknown>;

/** GET /api/incidents — recorded events. */
export const getIncidents = async (
  scope: ScopeFilter = {},
  filters: { incident_type?: string; severity?: string; from?: string; to?: string } = {},
): Promise<ServiceResult<HistoricalIncident[]>> => {
  const res = await get<Raw[]>(`/incidents${qs(scope, filters)}`);
  return { ...res, data: res.data.map(A.adaptIncident) };
};

/** GET /api/reports/field */
export const getFieldReports = async (
  scope: ScopeFilter = {},
  filters: { verification?: string; sync_status?: string } = {},
): Promise<ServiceResult<IncidentReport[]>> => {
  const res = await get<Raw[]>(`/reports/field${qs(scope, filters)}`);
  return { ...res, data: res.data.map(A.adaptFieldReport) };
};

export interface FieldReportDraft {
  incidentType: string;
  description: string;
  districtId: string;
  roadOrVillage: string;
  lat: number;
  lng: number;
  gpsAccuracyM?: number;
  severity: string;
  reporterType: string;
  reporterName: string;
  reporterContact?: string;
  /** Stable client key. Resubmitting the same key returns the original record. */
  clientId: string;
  deviceId?: string;
  files?: File[];
}

/**
 * POST /api/reports/field (multipart).
 *
 * `clientId` is what makes an offline queue safe to replay: a device that is not
 * sure whether its last submission landed can simply send it again, and the server
 * returns the original record instead of creating a duplicate incident.
 */
export const submitFieldReport = async (
  draft: FieldReportDraft,
): Promise<ServiceResult<IncidentReport>> => {
  const form = new FormData();
  form.append("incident_type", draft.incidentType);
  form.append("description", draft.description);
  form.append("district_id", draft.districtId);
  form.append("road_or_village", draft.roadOrVillage);
  form.append("lat", String(draft.lat));
  form.append("lng", String(draft.lng));
  form.append("severity", draft.severity);
  form.append("reporter_type", draft.reporterType);
  form.append("reporter_name", draft.reporterName);
  form.append("client_id", draft.clientId);
  if (draft.gpsAccuracyM !== undefined) form.append("gps_accuracy_m", String(draft.gpsAccuracyM));
  if (draft.reporterContact) form.append("reporter_contact", draft.reporterContact);
  if (draft.deviceId) form.append("device_id", draft.deviceId);
  for (const file of draft.files ?? []) form.append("files", file);

  const res = await postForm<Raw>("/reports/field", form);
  return { ...res, data: A.adaptFieldReport(res.data) };
};

/**
 * PATCH /api/reports/field/:id/verification.
 *
 * Verification is load-bearing, not bookkeeping: rule R6 only fires on VERIFIED
 * reports, so an anonymous photo can never trigger a public evacuation message on
 * its own.
 */
export const setVerification = async (
  id: string,
  verification: "VERIFIED" | "REJECTED" | "PENDING",
  actor = "Duty officer",
  note = "",
): Promise<ServiceResult<IncidentReport>> => {
  const res = await patch<Raw>(`/reports/field/${encodeURIComponent(id)}/verification`, {
    verification,
    actor,
    note,
  });
  return { ...res, data: A.adaptFieldReport(res.data) };
};

/* ------------------------------------------------------------------ offline queue */

const QUEUE_KEY = "ner-ews.pending-field-reports";

/**
 * Reports captured with no connection.
 *
 * Held in localStorage rather than in React state because the case this exists for
 * is precisely the one where the page gets closed: a field officer in a valley with
 * no signal writes the report, locks the phone, and drives until there is a bar.
 */
export function queueOffline(draft: FieldReportDraft): void {
  try {
    const pending = readQueue();
    if (!pending.some((d) => d.clientId === draft.clientId)) {
      pending.push({ ...draft, files: undefined });
      localStorage.setItem(QUEUE_KEY, JSON.stringify(pending));
    }
  } catch {
    /* storage full or unavailable — the submission error is already surfaced */
  }
}

export function readQueue(): FieldReportDraft[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    return raw ? (JSON.parse(raw) as FieldReportDraft[]) : [];
  } catch {
    return [];
  }
}

function dropFromQueue(clientId: string): void {
  try {
    localStorage.setItem(
      QUEUE_KEY,
      JSON.stringify(readQueue().filter((d) => d.clientId !== clientId)),
    );
  } catch {
    /* ignore */
  }
}

/** Drain the queue. Safe to call repeatedly — submission is idempotent by clientId. */
export async function syncQueue(): Promise<{ synced: number; remaining: number }> {
  let synced = 0;
  for (const draft of readQueue()) {
    try {
      await submitFieldReport(draft);
      dropFromQueue(draft.clientId);
      synced += 1;
    } catch {
      break;      // still offline; keep the rest and try again on the next reconnect
    }
  }
  return { synced, remaining: readQueue().length };
}
