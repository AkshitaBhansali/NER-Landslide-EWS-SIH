# API contract

Base URL `http://localhost:8000`. All payloads are **snake_case**, matching
`data_pipeline/schema.py`. Append `?case=camel` to any endpoint to receive
camelCase instead — see [Casing](#casing).

Common query parameters on list endpoints:

| Param | Meaning |
|---|---|
| `state` | State code (`AS`, `ML`, …) or `ALL` |
| `district` | District id (`as-dima-hasao`) or `ALL` |
| `case` | `camel` to receive camelCase |

`district` wins over `state`. Omitting both returns the whole region.

---

## Casing

`INTEGRATION.md` says the backend sends snake_case and `adapters.ts` maps it. That
remains the canonical contract. `?case=camel` exists for two reasons:

1. Akshita can set `DATA_SOURCE = "api"` and get a working console **today**, before
   the adapters are finished.
2. During integration week it isolates a bug to the adapter layer in ten seconds —
   if `?case=camel` works and the default does not, the bug is in `adapters.ts`.

```bash
curl 'localhost:8000/api/risk/zones?district=as-dima-hasao'              # risk_score
curl 'localhost:8000/api/risk/zones?district=as-dima-hasao&case=camel'   # riskScore
```

---

## Risk — `/api/risk`

| Method | Path | Returns |
|---|---|---|
| GET | `/api/risk/zones` | `RiskZone[]`, sorted by score desc. Filters: `level`, `min_score` |
| GET | `/api/risk/zones/{id}` | `RiskZone` |
| GET | `/api/risk/zones/{id}/explain` | Full LSI/TI breakdown, inputs, weights, bands |
| GET | `/api/risk/summary` | `RiskSummary` — the KPI grid |
| GET | `/api/risk/pipeline` | Pipeline strip counts |
| GET | `/api/risk/trend?district=&days=` | `RiskTrendPoint[]` |

### `RiskZone`

```json
{
  "id": "as-dima-hasao-z1",
  "name": "Dima Hasao Cutting Km 14",
  "district": "Dima Hasao",
  "district_id": "as-dima-hasao",
  "state_code": "AS",
  "center": { "lat": 25.35, "lng": 93.03 },

  "risk_score": 83.0,
  "risk_level": "CRITICAL",
  "alert_tier": "ORANGE",
  "probability": 0.903,
  "lsi": 0.7421,
  "ti": 0.8933,

  "slope_deg": 38.4, "elevation_m": 1100, "aspect_deg": 218,
  "soil_type": "Clayey", "landcover": "Cut Slope",

  "rainfall_24h_mm": 142.6, "rainfall_72h_mm": 288.1, "rainfall_7d_mm": 431.0,
  "antecedent_precip_index": 41.2, "soil_moisture_pct": 88.4,

  "sensor_confidence": 74.2,
  "contributing_factors": {
    "slope_deg": 0.181, "soil_type": 0.113, "landcover": 0.081, "terrain": 0.052,
    "soil_moisture_pct": 0.201, "rainfall_24h_mm": 0.199,
    "rainfall_72h_mm": 0.089, "rainfall_7d_mm": 0.048,
    "antecedent_precip_index": 0.036
  },
  "population": 12480,
  "recommended_action": "Evacuate exposed habitations, close the affected road …",
  "expected_window_hours": 6,
  "geometry": { "type": "Polygon", "coordinates": [[[93.04, 25.36], …]] },
  "source": "RULE_ENGINE",
  "model_version": null,
  "updated_at": "2026-09-01T06:10:36+00:00",
  "data_confidence": "SYNTHETIC"
}
```

`contributing_factors` sums to 1.0 — the UI renders them as comparable weighted
meters. `source` is `RULE_ENGINE` or `ML_MODEL`; when it is `ML_MODEL` the rule
engine will not overwrite the score.

---

## Alerts — `/api/alerts`

| Method | Path | Notes |
|---|---|---|
| GET | `/api/alerts` | Filters: `severity`, `status`, `trigger`, `active_only` |
| GET | `/api/alerts/{id}` | |
| GET | `/api/alerts/{id}/timeline` | **Audit trail** — events + dispatches + delivery |
| POST | `/api/alerts/{id}/acknowledge` | `{ actor?, note? }` → 409 if illegal |
| POST | `/api/alerts/{id}/dispatch` | Moves to IN_PROGRESS **and re-sends** |
| POST | `/api/alerts/{id}/resolve` | |
| GET | `/api/alerts/delivery/summary` | |
| POST | `/api/alerts/delivery/retry` | Drains the store-and-forward queue |

### `Alert`

```json
{
  "id": "ALT-1011",
  "severity": "CRITICAL",
  "tier": "ORANGE",
  "title": "High landslide probability detected",
  "zone_id": "ar-dibang-valley-z2",
  "location": "Dibang Valley Cutting Km 14",
  "district": "Dibang Valley", "district_id": "ar-dibang-valley", "state_code": "AR",
  "center": { "lat": 28.65, "lng": 95.9 },
  "issued_at": "2026-09-01T06:10:36+00:00",
  "risk_score": 83.0, "probability": 0.903,
  "trigger": "MODEL_PROBABILITY",
  "trigger_detail": "Classifier probability 90.3% above the 60% dispatch cut-off",
  "rule_id": "R1",
  "expected_window_hours": 6,
  "affected_roads": ["NH-102B · Dibang Valley"],
  "affected_villages": ["Rangpo Basti"],
  "population_affected": 640,
  "recommended_action": "Evacuate exposed habitations, …",
  "status": "NEW",
  "acknowledged_by": null, "acknowledged_at": null,
  "dispatched_at": null, "resolved_at": null,
  "sensor_confidence": 74.2,
  "low_confidence": false,
  "escalation_count": 0
}
```

**Lifecycle.** `NEW → ACKNOWLEDGED → IN_PROGRESS → RESOLVED`. Any other transition
returns **409**. `RESOLVED` is terminal.

**`/timeline` is the artefact that matters after an event**, when the question stops
being "did the model work" and becomes "was the warning issued, and did it arrive":

```json
{
  "alert": { … },
  "events": [
    { "at": "…", "event": "CREATED",    "actor": "system",    "detail": "R1 MODEL_PROBABILITY: …" },
    { "at": "…", "event": "ESCALATED",  "actor": "system",    "detail": "HIGH -> CRITICAL: …" },
    { "at": "…", "event": "ACKNOWLEDGED","actor": "DDMA Dibang Valley", "detail": "" }
  ],
  "dispatches": [
    { "audience": "AUTHORITY", "language": "en", "channel": "SMS",
      "msisdn": "+9190123****", "status": "SENT", "attempts": 1,
      "body": "[ORANGE] Landslide CRITICAL - Dibang Valley …" }
  ],
  "delivery": { "total": 5, "by_status": { "SENT": 5 }, "provider": "console" }
}
```

---

## Sensors — `/api/sensors`

| Method | Path | Notes |
|---|---|---|
| GET | `/api/sensors` | Filters: `status`, `sensor_type`, `zone_id`. Sorted worst-health first |
| GET | `/api/sensors/summary` | Fleet KPIs + `health_weights` |
| GET | `/api/sensors/{id}` | |
| GET | `/api/sensors/{id}/readings?hours=` | |

```json
{
  "sensor_id": "NER-AS-0101", "id": "NER-AS-0101",
  "name": "Dima Hasao · Tiltmeter",
  "zone_id": "as-dima-hasao-z1",
  "district": "Dima Hasao", "district_id": "as-dima-hasao", "state_code": "AS",
  "location": { "lat": 25.36, "lng": 93.04 },
  "sensor_type": "TILTMETER", "reading": 2.84, "unit": "°",
  "status": "DEGRADED", "health_score": 61.4,
  "health_sub_scores": {
    "completeness": 1.0, "validity": 1.0,
    "stability": 0.42, "noise": 0.88, "comms": 0.61
  },
  "battery_pct": 34, "rssi_dbm": -97, "expected_interval_s": 3600,
  "last_seen": "2026-09-01T05:48:00+00:00",
  "risk_contribution": 0.22,
  "maintenance_note": "Drift detected — recalibration recommended.",
  "installed_on": "2025-11-02T00:00:00+00:00",
  "transport": "LORAWAN"
}
```

Health weights match the pipeline exactly: completeness 0.25, validity 0.25,
stability 0.20, noise 0.15, comms 0.15. A **silent** sensor is `OFFLINE` regardless
of how clean its last data looked — ≥8 missed intervals forces the status.

---

## GIS and assets

| Method | Path | Returns |
|---|---|---|
| GET | `/api/gis/layers` | Layer registry with `available` + `source_hint` |
| GET | `/api/gis/layers/{id}` | GeoJSON `FeatureCollection`, or **409** if not served |
| GET | `/api/gis/terrain?district=` | `TerrainProfile` incl. 16×16 `dem_grid` |
| GET | `/api/gis/infrastructure` | Exposure = risk × importance, sorted desc |
| GET | `/api/roads` | `RoadStatus[]`, BLOCKED first |
| GET | `/api/villages` | `Village[]` |
| GET | `/api/infrastructure` | `Infrastructure[]` |

Live layers: `risk_heatmap` (Polygon), `sensors` / `villages` / `infrastructure` /
`rainfall` / `incidents` (Point), `roads` (LineString).
Not yet served: `terrain`, `dem`, `satellite` → **409** with the reason in the body.

> **Ayush:** flipping `available: true` in `routers/gis.py:LAYERS` and adding a
> branch in `layer()` is all a new layer needs. `dem_grid` is read as `len(grid)`,
> not hard-coded 16 — a 64×64 real raster drops straight in.

---

## Incidents and field reports

| Method | Path | Notes |
|---|---|---|
| GET | `/api/incidents` | Filters: `incident_type`, `severity`, `from`, `to` |
| GET | `/api/reports/field` | Filters: `verification`, `sync_status` |
| POST | `/api/reports/field` | **multipart/form-data** → 201 |
| PATCH | `/api/reports/field/{id}/verification` | `{ verification, actor?, note? }` |
| GET | `/api/media/{report_id}/{filename}` | Serves an attachment |

```bash
curl -X POST localhost:8000/api/reports/field \
  -F incident_type=CRACK \
  -F description='Tension crack above the cutting, widening since morning' \
  -F district_id=as-dima-hasao -F road_or_village='NH-27 · Mahur section' \
  -F lat=25.3612 -F lng=93.0451 -F severity=HIGH \
  -F reporter_type=FIELD_OFFICER -F reporter_name='PWD Field Unit 3' \
  -F client_id=device7-0042 -F device_id=field-tablet-7 \
  -F files=@crack.jpg
```

Accepted media: JPEG, PNG, WebP, HEIC, MP4, MOV, WebM. Max 25 MB per file;
anything else returns **415** / **413**.

Reports always arrive `verification: "PENDING"`. **Rule R6 only fires on VERIFIED
reports** — an anonymous photo must never be able to trigger a public evacuation
SMS on its own. Verification is therefore a load-bearing authority action, not
bookkeeping.

`client_id` makes submission idempotent: resubmitting the same `client_id` returns
the original record instead of creating a duplicate.

---

## Reports and model

| Method | Path | Notes |
|---|---|---|
| GET | `/api/reports/quarterly?district=` | The **whole** report object |
| POST | `/api/reports/generate` | → `{ job_id, status }` |
| GET | `/api/reports/jobs/{job_id}` | |
| GET | `/api/model/performance` | Latest `ModelRun` + caveat |
| POST | `/api/model/predict` | Publish model output (below) |

> **Nitin:** one endpoint returns the whole report on purpose. The report is a single
> publication with internally consistent figures; assembling it from eight
> independent calls is how a KPI grid ends up disagreeing with the chart below it.
> Sections: `kpis`, `risk_trend`, `rainfall_vs_risk`, `alerts_by_severity`,
> `sensor_performance`, `risk_calendar`, `district_comparison`,
> `infrastructure_impact`, `response_metrics`, `critical_events`,
> `model_performance`, `recommendations`.

---

## Ingest

| Method | Path | Notes |
|---|---|---|
| POST | `/api/ingest/readings` | Batch sensor readings. Idempotent |
| POST | `/api/model/predict` | Model output. Triggers a risk cycle |
| POST | `/api/ingest/weather` | Weather observations |
| POST | `/api/ingest/imd/pull` | Pull from configured IMD endpoint |
| POST | `/api/engine/run?send=true` | Trigger a cycle by hand |

### Readings — `POST /api/ingest/readings`

```json
{ "readings": [
  { "sensor_id": "NER-AS-0101", "timestamp": "2026-09-01T06:00:00+00:00",
    "value": 2.84, "unit": "°", "quality_flag": "OK",
    "battery_pct": 34, "rssi_dbm": -97 }
]}
```
→ `{ "accepted": 1, "duplicates": 0, "rejected": 0, "errors": [] }`

Duplicates are accepted silently. A LoRa gateway doing store-and-forward **will**
resend what it already sent; the unique constraint on `(sensor_id, timestamp)` makes
that harmless, so the gateway can be dumb and retry blindly.

### Predictions — `POST /api/model/predict`

> **Saksham:** this is your integration point.

```json
{
  "model_version": "rf-2026.09.01",
  "algorithm": "RandomForest",
  "metrics": { "roc_auc": 0.786, "recall": 0.850, "precision": 0.549 },
  "feature_importance": [ { "feature": "slope_deg", "importance": 0.866 } ],
  "evaluated_on": "8,000 held-out physics-simulated scenarios",
  "caveat": "Simulated scenarios, not observed events.",
  "predictions": [
    { "zone_id": "as-dima-hasao-z1", "risk_score": 84.2,
      "risk_level": "CRITICAL", "probability": 0.88,
      "contributing_factors": { "slope_deg": 0.42, "rainfall_24h_mm": 0.31 } }
  ]
}
```

- If you emit `risk_level`, **your value wins** over the local band function — you
  may have calibrated against thresholds this service does not know about, and
  silently re-binning your output would misrepresent it.
- Posting sets `source: "ML_MODEL"`, and the rule engine stops overwriting that zone.
- A risk cycle runs **immediately** on publish. A 15-minute delay on a critical score
  is 15 minutes of a warning that existed but was not sent.

---

## Offline sync — `/api/sync`

See `OFFLINE_AND_DELIVERY.md` for the full design.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/sync/bundle?district=` | District snapshot + `ETag` |
| GET | `/api/sync/delta?since=` | Changed-since feed |
| POST | `/api/sync/batch` | Idempotent replay of the device queue |
| GET | `/api/sync/status` | Ledger stats + conflict policy |

---

## Platform

| Method | Path |
|---|---|
| GET | `/api/health`, `/api/system/status` |
| GET | `/api/districts` — 8 states, 30 districts |
| GET | `/api/weather?district=`, `/api/weather/all` |
| GET | `/api/notifications`; POST `/api/notifications/{id}/read`, `/read-all` |
| GET | `/api/settings/thresholds`; PATCH `/api/settings/thresholds/{district_id}` |
| GET | `/api/settings/languages`, `/api/recipients` |
| POST | `/api/auth/login` |
| WS | `/api/ws` — live push |

`GET /api/weather` with no district returns the district **closest to breaching its
threshold**, because on a regional dashboard that is the only one anybody needs.

---

## Auth

Off by default (`AUTH_ENABLED=false`) so the console needs zero setup. When enabled:

```bash
curl -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"ddma.dimahasao","password":"demo1234"}'
```

Seeded users (all `demo1234`): `admin` (STATE_ADMIN), `ddma.dimahasao` (DDMA),
`field.pwd3` (FIELD_OFFICER), `viewer` (VIEWER).

Roles rank `VIEWER < FIELD_OFFICER < DDMA < STATE_ADMIN`. Acknowledge/dispatch/
verify need DDMA; threshold edits need STATE_ADMIN.

---

## Errors

`ServiceError`-compatible shape. HTTP codes carry meaning:

| Code | Meaning |
|---|---|
| 400 | Malformed input |
| 401 / 403 | Auth / insufficient role |
| 404 | Record genuinely does not exist |
| **409** | **Legal record, illegal operation** — alert transition, or a registered GIS layer with no data source |
| 413 / 415 | Media too large / wrong type |
| 502 | Upstream (IMD, SMS gateway) failed |

409 rather than 404 for unserved layers is deliberate: the layer is real and
registered, it just has no source yet, so the UI shows a disabled toggle with the
reason instead of a dead button.


---

## Model and streaming (added during integration)

### `GET /api/model/status`

Whether the trained classifier is loaded, on which features, and whether it shares
the training script's `risk_output_schema()` contract. Exists because "is the model
actually running?" was previously unanswerable from outside the process — the
platform reported ML precedence in its architecture while scoring every zone with
the fallback rules.

```json
{
  "available": true,
  "algorithm": "RandomForestClassifier",
  "model_version": "randomforestclassifier-13547689",
  "features": ["slope_deg", "rainfall_24h_mm", "rainfall_72h_mm",
               "rainfall_7d_mm", "antecedent_precip_index"],
  "shares_training_contract": true,
  "warning": null,
  "sklearn_version": "1.8.0"
}
```

`available: false` is not an error state. Inference dependencies are optional; the
rule engine scores everything without them and `error` says which import failed.

### `POST /api/model/score`

Runs inference over every zone immediately. Returns `{scored, applied,
rule_engine_kept, model_version}`. `applied + rule_engine_kept == scored`.

Precedence: the more severe of the classifier and the rule engine is published. The
classifier sees five observable features; the rules see measured slope movement,
verified road blockages and soil at saturation. Both numbers are retained on the
zone (`risk_score`, `model_probability`).

Zones with a live external publish (see below) are skipped.

### `POST /api/model/predict`

Unchanged contract. Now additionally stamps `model_published_at`, which makes the
prediction authoritative for `MODEL_PUBLISH_TTL_MIN` minutes: neither the rule
engine nor in-process inference will overwrite the score in that window. Inputs
(rainfall, soil moisture, sensor confidence) continue to refresh throughout, so the
zone does not go stale behind the held score.

### `GET /api/stream` — Server-Sent Events

Filters, comma-separated, applied at publish time:

| Parameter | Example |
|---|---|
| `events` | `events=sensor_reading,zone_alert` |
| `zones` | `zones=nl-kohima-z1` |
| `sensors` | `sensors=NER-NL-5001` |
| `sensor_types` | `sensor_types=PIEZOMETER,TILTMETER` |

Envelope:

```
event: zone_risk
data: {"seq": 10, "event": "zone_risk", "emitted_at": "...", "data": { }}
```

`seq` is monotonic. On backpressure the bus drops the subscriber's oldest queued
event, never the newest and never by disconnecting — for an early-warning stream the
latest reading is the operationally relevant one. A `seq` gap tells the client to
refill from the REST history endpoints.

Event catalogue: `sensor_reading`, `zone_risk`, `zone_alert`, `sensor_health`,
`sensor_fault`, `tick`.

### `GET /api/stream/status`

Subscriber count, published total, per-connection drop counters — whether anyone is
falling behind.
