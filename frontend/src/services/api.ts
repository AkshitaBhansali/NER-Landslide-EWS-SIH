/**
 * Transport layer.
 *
 * Every service in this folder returns a `ServiceResult<T>` and talks to the
 * backend. There is no second data source: the mock generator that used to sit
 * behind a `DATA_SOURCE` switch has been removed, because a console with two data
 * paths is a console where the one you are not looking at silently rots.
 *
 * Backend payloads are snake_case (matching `data_pipeline/schema.py`).
 * `adapters.ts` is the only file that maps names onto the camelCase UI types — if a
 * field is renamed on the server, that is the one file to change.
 *
 * Provenance rather than "demo": the backend states what each payload is made of
 * via the `X-Data-Confidence` header, and the UI labels it honestly (Simulated
 * telemetry, Historical, Model-derived) instead of stamping "DEMO" on the page.
 */

import type { ServiceResult } from "@/types";

/** Base URL. Configure with VITE_API_BASE_URL; the dev server proxies /api. */
export const API_BASE_URL: string =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "/api";

/** How long a request may hang before we stop waiting and show the last good data. */
const TIMEOUT_MS = Number(import.meta.env?.VITE_API_TIMEOUT_MS ?? 15000);

export class ServiceError extends Error {
  readonly code: string;
  readonly status?: number;
  constructor(message: string, code = "SERVICE_ERROR", status?: number) {
    super(message);
    this.name = "ServiceError";
    this.code = code;
    this.status = status;
  }
}

/**
 * Turn a failure into something an operator can act on.
 *
 * "Something went wrong" tells a duty officer nothing at 3am. Each branch below
 * says what is actually unavailable and what the console is showing instead.
 */
function describe(status: number, body: string): string {
  switch (status) {
    case 0:
      return "Cannot reach the monitoring service. Showing the last synchronised data.";
    case 401:
    case 403:
      return "Your account does not have permission for this action.";
    case 404:
      return "That record no longer exists. It may have been resolved or removed.";
    case 409:
      return body || "That action is not valid for the current state of this record.";
    case 413:
      return "The attachment is too large. Maximum 25 MB per file.";
    case 415:
      return "That file type is not accepted. Use JPEG, PNG, WebP, MP4 or MOV.";
    case 502:
      return "An upstream service (weather or messaging) is not responding.";
    default:
      if (status >= 500) return "The monitoring service reported an internal error.";
      return body || `Request failed (${status}).`;
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") return JSON.stringify(detail);
    return "";
  } catch {
    return "";
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<ServiceResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
    const res = await fetch(`${API_BASE_URL}${path}`, {
      signal: controller.signal,
      ...init,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(init?.headers ?? {}),
      },
    });
    if (!res.ok) {
      throw new ServiceError(
        describe(res.status, await readError(res)),
        `HTTP_${res.status}`,
        res.status,
      );
    }
    return {
      data: (await res.json()) as T,
      dataConfidence: res.headers.get("X-Data-Confidence") ?? undefined,
      fetchedAt: new Date().toISOString(),
    };
  } catch (err) {
    if (err instanceof ServiceError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ServiceError(
        "The monitoring service did not respond in time. Showing the last synchronised data.",
        "TIMEOUT",
      );
    }
    throw new ServiceError(describe(0, ""), "NETWORK", 0);
  } finally {
    clearTimeout(timer);
  }
}

export const get = <T,>(path: string) => request<T>(path);

export const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const patch = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) });

export const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

export const postForm = <T,>(path: string, form: FormData) =>
  request<T>(path, { method: "POST", body: form });

export interface ScopeFilter {
  /** State code, or "ALL". */
  stateCode?: string;
  /** District id, or "ALL". */
  districtId?: string;
}

/** Scope as a query string. District wins over state, matching the API contract. */
export function qs(
  scope: ScopeFilter = {},
  extra: Record<string, string | number | undefined> = {},
): string {
  const params = new URLSearchParams();
  if (scope.districtId && scope.districtId !== "ALL") params.set("district", scope.districtId);
  else if (scope.stateCode && scope.stateCode !== "ALL") params.set("state", scope.stateCode);
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined && value !== "" && value !== "ALL") params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

/** Wrap an already-computed value in the standard envelope. */
export const wrap = <T,>(data: T): ServiceResult<T> => ({
  data,
  fetchedAt: new Date().toISOString(),
});
