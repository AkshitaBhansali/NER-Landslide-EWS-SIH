# Frontend integration — the exact change

For Akshita. Nothing in `src/pages` or `src/components` changes. The seam is
`src/services`, exactly as `INTEGRATION.md` describes.

---

## The 60-second version

```bash
# terminal 1
cd backend && ./run.sh                     # :8000

# terminal 2
echo 'VITE_API_BASE_URL=http://localhost:8000/api' > .env.local
npm run dev                                # :5173
```

Then one line in `src/services/api.ts`:

```diff
- export const DATA_SOURCE: DataSource = "mock";
+ export const DATA_SOURCE: DataSource = "api";
```

CORS already allows `:5173` and `:4173`.

---

## Option A — ship before `adapters.ts` is finished

The backend can emit camelCase directly. Append `case=camel` to every request and
the adapters become a no-op:

```ts
// src/services/api.ts
export const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? "/api";

// Force camelCase from the server so adapters are a pass-through for now.
const CAMEL_MODE = true;

function withCase(path: string): string {
  if (!CAMEL_MODE) return path;
  return path + (path.includes("?") ? "&" : "?") + "case=camel";
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${withCase(path)}`, {
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ServiceError(detail || res.statusText, `HTTP_${res.status}`);
  }
  return res.json() as Promise<T>;
}
```

Then in each service, the adapter call can pass through:

```ts
export const getRiskZones = (scope: ScopeFilter) =>
  IS_DEMO
    ? resolveMock(() => RISK_ZONES.filter(inScope(scope)))
    : request<RiskZone[]>(`/risk/zones?${qs(scope)}`);   // already camelCase
```

**Set `CAMEL_MODE = false` once `adapters.ts` is done.** The canonical contract is
snake_case; `case=camel` is a bridge, not the destination. It also gives you a
ten-second bug isolation during integration week — if `case=camel` works and the
default doesn't, the bug is in `adapters.ts`, not the backend.

## Option B — canonical snake_case

Leave `CAMEL_MODE = false` and keep `adapters.ts`. Field names match
`API_CONTRACT.md` exactly. Nested keys the UI reads (`contributing_factors`,
`health_sub_scores`) are plain snake_case objects.

---

## `qs(scope)` must emit these names

```ts
export const qs = (scope: ScopeFilter) => {
  const p = new URLSearchParams();
  if (scope.stateCode && scope.stateCode !== "ALL") p.set("state", scope.stateCode);
  if (scope.districtId && scope.districtId !== "ALL") p.set("district", scope.districtId);
  return p.toString();
};
```

`district` wins over `state`; omitting both returns the whole region — same
precedence your `inScope()` already uses.

---

## Endpoint map — your file → my route

| Service function | Route |
|---|---|
| `getRiskZones` | `GET /risk/zones` |
| `getRiskZone` | `GET /risk/zones/:id` |
| `getRiskSummary` | `GET /risk/summary` |
| `getPipelineStatus` | `GET /risk/pipeline` |
| `getRiskTrend` | `GET /risk/trend?district=&days=` |
| `getAlerts` / `getActiveAlerts` | `GET /alerts` (`?active_only=true`) |
| `acknowledgeAlert` | `POST /alerts/:id/acknowledge` |
| `dispatchResponse` | `POST /alerts/:id/dispatch` |
| `getSensors` | `GET /sensors` |
| `getSensor` | `GET /sensors/:id` |
| `getSensorReadings` | `GET /sensors/:id/readings?hours=` |
| `getSensorFleetSummary` | `GET /sensors/summary` |
| `getGisLayers` | `GET /gis/layers` |
| `getGisLayer` | `GET /gis/layers/:id` |
| `getTerrainProfile` | `GET /gis/terrain?district=` |
| `getInfrastructure` | `GET /gis/infrastructure` |
| `getRoads` / `getVillages` | `GET /roads` · `GET /villages` |
| `getIncidents` | `GET /incidents` |
| `getFieldReports` | `GET /reports/field` |
| `submitFieldReport` | `POST /reports/field` (multipart) |
| `setVerification` | `PATCH /reports/field/:id/verification` |
| `getWeather` | `GET /weather?district=` |
| `getReportSummary` | `GET /reports/quarterly?district=` |
| `generateReport` | `POST /reports/generate` |
| `getSystemStatus` | `GET /system/status` |
| `getNotifications` | `GET /notifications` |

---

## Two things that need real work on your side

### 1. `submitFieldReport` becomes multipart

```ts
export async function submitFieldReport(
  draft: FieldReportDraft,
  mode: "SUBMIT" | "OFFLINE",
): Promise<IncidentReport> {
  // Mint the client_id AT CAPTURE, not at send. This is the whole idempotency
  // mechanism — an ID generated on send is a different ID on every retry.
  const clientId = draft.clientId ?? crypto.randomUUID();

  if (mode === "OFFLINE") {
    await queueInIndexedDb({ ...draft, clientId });   // yours to write
    return { ...draft, id: clientId, syncStatus: "PENDING_SYNC",
             verification: "PENDING" } as IncidentReport;
  }

  const fd = new FormData();
  fd.set("incident_type", draft.incidentType);
  fd.set("description", draft.description ?? "");
  fd.set("district_id", draft.districtId);
  fd.set("road_or_village", draft.roadOrVillage ?? "");
  fd.set("lat", String(draft.location.lat));
  fd.set("lng", String(draft.location.lng));
  fd.set("severity", draft.severity);
  fd.set("reporter_type", draft.reporterType);
  fd.set("reporter_name", draft.reporterName ?? "Anonymous");
  fd.set("client_id", clientId);
  fd.set("device_id", getDeviceId());
  draft.media.forEach((f) => fd.append("files", f));

  return request<IncidentReport>("/reports/field", { method: "POST", body: fd });
  // NOTE: do not set Content-Type — the browser sets the multipart boundary.
}
```

Limits enforced server-side: 25 MB per file; JPEG/PNG/WebP/HEIC/MP4/MOV/WebM only.
Anything else returns 413 or 415 with a readable message, so surface `err.message`
directly in the form.

### 2. Background sync

```ts
export async function flushOfflineQueue(): Promise<void> {
  const queued = await readQueueFromIndexedDb();
  if (!queued.length) return;

  const res = await request<BatchResult>("/sync/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      device_id: getDeviceId(),
      operations: queued.map((q) => ({
        op: "FIELD_REPORT",
        client_id: q.clientId,
        payload: toSnakePayload(q),
      })),
    }),
  });

  // ACCEPTED and DUPLICATE both mean "the server has it" — clear both.
  for (const r of res.results) {
    if (r.status === "ACCEPTED" || r.status === "DUPLICATE") {
      await removeFromQueue(r.client_id);
    }
  }
}
```

Treating `DUPLICATE` as success is the point of the whole design. If you retry on
duplicate, the queue never drains.

Attach it to the `online` listener `AppContext` already has:

```ts
useEffect(() => {
  const onOnline = () => { setConnection("ONLINE"); void flushOfflineQueue(); };
  window.addEventListener("online", onOnline);
  return () => window.removeEventListener("online", onOnline);
}, []);
```

---

## Optional: drop the 30-second polling

There's a websocket at `ws://localhost:8000/api/ws`:

```ts
const ws = new WebSocket(`${API_BASE_URL.replace(/^http/, "ws")}/ws`);
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "RISK_CYCLE") reloadAlerts();
};
```

On a district office's metered link, replacing a 30-second poll with a push
subscription is the difference between usable and not. Keep the poll as a fallback
if the socket fails to open.

---

## Things that will look different from the mock

These are all correct; don't "fix" them:

- **Fewer alerts than the mock.** The mock made one alert per zone above 30. The real
  engine dedupes per hillside, so one slope with three rules firing is one alert with
  the dominant `trigger`, not three.
- **`alert_tier` is new** and does **not** track `risk_level`. Bands drive display
  (≥80/60/35); tiers drive who gets an SMS (≥86/66/41). A zone can read CRITICAL and
  still be ORANGE. Both are editable at `/api/settings/thresholds` — that page can be
  wired to real data now.
- **New fields** you may want to surface: `low_confidence` (badge it — it means the
  warning did not go to the public), `escalation_count`, `rule_id`, `lsi`/`ti`.
- **`GET /gis/layers/dem`** returns **409**, not 404 or an empty array, with the
  reason in the body. Your disabled-toggle path should read that reason.
- **`sync_status` is always `SYNCED`** from the server. `PENDING_SYNC` is a
  client-side state that only exists in your IndexedDB queue.

---

## Checklist before the demo

- [ ] `DATA_SOURCE = "api"`, `.env.local` set, both servers running
- [ ] Every page loads; no console errors
- [ ] Acknowledge an alert → survives a refresh (this is the headline proof the
      backend is real — writes used to be lost)
- [ ] Submit a field report with a photo → appears in the list with media
- [ ] Verify that report as an authority → check `/alerts` for a `ROAD_BLOCKAGE`
      trigger on the next `POST /api/engine/run`
- [ ] DevTools offline → console still renders from cache, reports queue
- [ ] Back online → queue drains, no duplicates
- [ ] `POST /api/engine/run` live on stage — new alerts appear without a refresh if
      the websocket is wired
