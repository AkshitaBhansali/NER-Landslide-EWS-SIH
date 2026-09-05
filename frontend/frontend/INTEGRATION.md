# Integration guide

How the real system replaces the demo data, per owner. Nothing in `src/pages` or `src/components` needs to change for any of this — the seam is `src/services`.

---

## 0. The switch

`src/services/api.ts`:

```ts
export const DATA_SOURCE: DataSource = "mock";   // -> "api"
export const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? "/api";
```

Set `DATA_SOURCE = "api"` and provide `VITE_API_BASE_URL`. Each service already has both branches:

```ts
export const getRiskZones = (scope: ScopeFilter) =>
  IS_DEMO
    ? resolveMock(() => RISK_ZONES.filter(inScope(scope)))
    : request<RiskZoneDTO[]>(`/risk/zones?${qs(scope)}`).then(r => r.map(adaptRiskZone));
```

`resolveMock` adds 220 ms of latency deliberately, so loading and error states are exercised during development rather than discovered in production.

---

## 1. Backend & alert engine — Krish Modi

### Endpoints the frontend is written against

```
GET  /api/risk/zones?state=&district=        -> RiskZone[]
GET  /api/risk/zones/:id                     -> RiskZone
GET  /api/risk/summary?state=&district=      -> RiskSummary
GET  /api/risk/trend?district=&days=         -> RiskTrendPoint[]
GET  /api/alerts?severity=&district=&status= -> Alert[]
POST /api/alerts/:id/acknowledge             -> Alert
POST /api/alerts/:id/dispatch                -> Alert
GET  /api/sensors?district=&status=          -> Sensor[]
GET  /api/sensors/:id                        -> Sensor
GET  /api/sensors/:id/readings?hours=        -> SensorReading[]
GET  /api/sensors/summary?district=          -> SensorFleetSummary
GET  /api/gis/layers                         -> GISLayer[]
GET  /api/gis/layers/:id?district=           -> GeoJSON FeatureCollection
GET  /api/gis/terrain?district=              -> TerrainProfile
GET  /api/gis/infrastructure?district=       -> Infrastructure[]
GET  /api/roads?district=                    -> RoadStatus[]
GET  /api/villages?district=                 -> Village[]
GET  /api/incidents?district=&from=&to=      -> HistoricalIncident[]
GET  /api/reports/field?district=            -> IncidentReport[]
POST /api/reports/field                      -> IncidentReport  (multipart)
GET  /api/weather?district=                  -> WeatherData
GET  /api/reports/quarterly?district=        -> ReportSummary
POST /api/reports/generate                   -> { jobId, status }
GET  /api/system/status                      -> SystemStatus
GET  /api/notifications                      -> AppNotification[]
```

### Payload shape

Send **snake_case**, matching `data_pipeline/schema.py`. `src/services/adapters.ts` is the only file that maps names:

```ts
adaptRiskZone({ risk_score, risk_level, probability, contributing_factors, ... })
adaptSensor({ sensor_id, zone_id, sensor_type, battery_pct, rssi_dbm, expected_interval_s, ... })
```

If a field name changes on the backend, change it in `adapters.ts` and nowhere else.

### Errors

`request()` throws `ServiceError(message, code)`. `useAsync` catches it and renders `ErrorState` with a Retry button, per section — one failing panel never takes down the page.

### Alert lifecycle

The UI drives `NEW → ACKNOWLEDGED → IN_PROGRESS → RESOLVED`. `acknowledgeAlert` and `dispatchResponse` currently write to an in-memory override map in `alertService.ts`; replace those two function bodies with POSTs and the buttons, toasts and notification pushes keep working unchanged.

### Realtime

Polling intervals live in `useAsync` consumers. If you add a WebSocket or SSE feed, push into the same services and call the existing `reload()`.

---

## 2. ML & risk scoring — Saksham

`risk_output_schema()` maps directly onto `RiskZone`:

| Python | UI type |
|---|---|
| `risk_score` (0–100) | `RiskZone.riskScore` |
| `risk_level` | `RiskZone.riskLevel` — normalised by `normaliseRiskLevel` |
| `probability` | `RiskZone.probability` |
| `contributing_factors` | `RiskZone.contributingFactors` — rendered as weighted meters in the zone panel |

Band cut-offs (`≥80 CRITICAL`, `≥60 HIGH`, `≥35 MODERATE`) live in `riskLevelFromScore` in `src/utils/index.ts` and are surfaced as editable thresholds on `/settings`. If the model emits its own `risk_level`, that value wins; the local function is only the fallback.

Model metrics displayed on `/reports` and `/settings` come from `MODEL_PERFORMANCE` in `src/data/mock/reports.ts`. Point that at a real `/api/model/performance` when the evaluation run is versioned. **Keep the caveat text** — those numbers are from ~8,000 physics-simulated scenarios, not validated field outcomes.

---

## 3. Data pipeline & sensor health — Eisa

`SENSOR_READING_SCHEMA` maps onto `SensorReading`. The health score in the sensor drawer reproduces the pipeline's own weighting so the console and the pipeline never disagree:

| Sub-score | Weight |
|---|---|
| completeness | 0.25 |
| validity | 0.25 |
| stability | 0.20 |
| noise | 0.15 |
| comms | 0.15 |

Statuses are `Healthy / Degraded / Failed`, mapped by `adaptSensorStatus`. Replace the computed sub-scores with the pipeline's values as soon as they are exposed — the drawer already renders whatever it is given.

`HISTORICAL_EVENT_SCHEMA` fields (`slope_deg`, `rainfall_24h_mm`, `rainfall_72h_mm`, `rainfall_7d_mm`, `antecedent_precip_index`, `soil_moisture_pct`, `data_confidence`) are all present on `RiskZone` and shown in the zone detail panel. `dataConfidence` is currently `"SYNTHETIC"` everywhere and drives the demo labelling — set it to the real value and the labels resolve themselves.

---

## 4. GIS, DEM & 3D terrain — Ayush

Three plug points:

**(a) Layers.** `src/data/mock/gis.ts` holds `GIS_LAYERS`, a registry of ten layers with `available` flags and a `sourceHint`. `gisService.getGisLayer(id, scope)` already returns a GeoJSON-shaped `FeatureCollection`. Serve real GeoJSON from `/api/gis/layers/:id` and flip `available: true` for `dem` and `satellite`. The layer toggles, legend and disabled states are all driven off this registry — no UI edit needed to add a layer.

**(b) Projection.** `src/components/map/projection.ts` is the single swap point. It exposes `project`, `projectCoord`, `pathFromCoords`, `polygonPoints` and `viewportFor` over a fixed viewBox. To move to MapLibre or Cesium, replace `RiskMap.tsx`'s SVG canvas with the map instance and feed the same layer data; every consumer already passes lat/lng, never pixels.

**(c) Terrain.** `TerrainProfile` carries `slopeDeg`, `elevationM`, `aspect`, `reliefM` and a 16×16 `demGrid`. The DEM panel and `Terrain3D.tsx` both read it. Swap `buildDemGrid` for real raster samples (Bhuvan / Cartosat DEM) at whatever resolution you serve; the components read `demGrid.length`, not a hard-coded 16.

Infrastructure exposure is computed as `risk × importance` in the generator and rendered on `/gis`; replace with your spatial-risk output if you compute it upstream.

---

## 5. Reports & analytics — Nitin

`reportService.getReportSummary(scopeId, scopeLabel)` returns one `ReportSummary` that feeds the whole `/reports` page: KPI grid, 90-day risk trend, rainfall-vs-risk with the threshold line, alerts by severity, monthly sensor performance, risk calendar heatmap, district comparison, infrastructure impact, response metrics, critical-event timeline and recommendations.

To take it over: implement `GET /api/reports/quarterly?district=` returning that shape, and `POST /api/reports/generate` returning a job handle. The page already handles the job's pending state.

- **EXPORT CSV** — `reportToCsv` + `downloadCsv`, client-side, works today.
- **DOWNLOAD PDF / PRINT** — both call `window.print()` against the print stylesheet in `components.css`. A server-side renderer can replace the PDF path; keep the print styles for the offline case.
- The report cover, `sec-head`, `callout`, `rec-item` and `disclaimer` classes deliberately reproduce the sample quarterly report supplied with the brief, so a generated PDF and the sample document look like the same publication.

---

## 6. Field & citizen reports — Akshita / persistence

Today `incidentService.submitFieldReport(draft, mode)` writes to a module-level array and returns a report with `syncStatus` of `PENDING_SYNC`, `SYNCED` or `FAILED`. `retrySync` moves a failed one along. Nothing survives a refresh.

**Recommended persistence path:**

1. **Draft + queue in IndexedDB** (not `localStorage` — media blobs are too big). One store for report metadata, one for attachments.
2. **Submit** posts `multipart/form-data` to `POST /api/reports/field`: a `report` JSON part plus one part per attachment. Server returns the canonical `IncidentReport` with an ID and `syncStatus: "SYNCED"`.
3. **Save offline** skips the network, marks `PENDING_SYNC`, and stays in the queue. The queue is already rendered on `/field-reports` with per-item state.
4. **Background sync** via a service worker's `sync` event, or on the `online` event that `AppContext` already listens to. Retry with backoff; mark `FAILED` after N attempts and surface the Retry button that already exists.
5. **Verification** (`UNVERIFIED / VERIFIED / REJECTED`) is an authority action — `PATCH /api/reports/field/:id/verification`. `setVerification` is the stub.
6. **GPS** uses `navigator.geolocation` with a district-centroid fallback so a report is never lost to a denied permission.

Reports from the public should be treated as **signals, not ground truth** — the UI keeps them visually separate from sensor-derived risk for exactly this reason.

---

## 7. What to check before a demo

- `npm run build` passes with `tsc -b` (strict, `noUnusedLocals`, `noUnusedParameters`).
- Every button navigates, opens a panel, mutates state, or is explicitly disabled with a reason. There are no dead controls.
- Every async section renders one of: loading skeleton, error with retry, empty state, or data.
- Turn off the network in devtools: the console still renders, the connection chip flips to Offline, and field reports queue instead of failing.
