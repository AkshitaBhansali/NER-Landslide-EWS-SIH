# NER Landslide Early Warning System

An operator-facing early-warning platform for the North Eastern Region: sensor
telemetry, data-quality scoring, physics-and-model risk prediction, a rule-based
alert engine with delivery routing, spatial risk and exposure analysis, field
reporting, and quarterly reporting — integrated into one system.

> **Research prototype.** It carries no authority to issue an official warning.
> Sensor telemetry is produced by a physics-informed simulator; risk scores are
> model-derived; recorded events come from a synthesised regional dataset. Every
> figure in the UI and in every generated report is labelled with its provenance.

---

## 1. Architecture

```
   simulated / ingested telemetry
                 |
     data quality + sensor health          <- health scored independently of risk
                 |
     risk engine  (LSI x 0.4 + TI x 0.6)   <- rule pass: physics + terrain
                 |
     trained classifier (RandomForest)     <- in-process inference each cycle;
                 |                            more severe of the two is published
     alert engine (R1-R7 + custom rules)   <- cooldown, escalation, dedup, confidence
                 |
     delivery routing (tier -> audience)   <- Green sends nothing; Red reaches the public
                 |
       backend API  +  stream bus          <- SSE and WebSocket, filtered per subscriber
                 |
          frontend dashboard


   DEM + terrain derivatives                field report
        |                                        |
   spatial risk surface                      incident
        |                                        |
   exposure = risk x importance            verification
        |                                        |
      GIS tab                          risk/alert engine (R6) -> dashboard + GIS


   historical events + risk history + alerts + sensors + exposure
                             |
                    analytics + report generation
```

The single most important structural decision: **health and risk are computed
independently and travel together.** A high reading and an unreliable instrument
look identical in raw data. Keeping them separate is what lets an alert say "high
risk, low confidence — verify" instead of either crying wolf or staying silent.

---

## 2. Folder structure

```
NER-Landslide-EWS/
├── backend/          FastAPI service — API, risk engine, alert engine, sync
│   ├── app/core/     risk, alerts, custom rules, sensor health, telemetry,
│   │                 GIS store, historical data, report renderer
│   ├── app/routers/  risk, alerts, custom alerts, sensors, gis, incidents,
│   │                 reports, platform, sync, ingest, simulation
│   └── tests/        75 tests
├── frontend/         React + TypeScript + Vite console
├── ml/
│   ├── pipeline/     model training, feature engineering, shared scoring contract
│   ├── data_pipeline/ cleaning, sensor health scoring, schema
│   ├── simulation/   physics slope model (infinite-slope factor of safety)
│   ├── streaming_api/ standalone real-time SSE/WebSocket service (runs on its own)
│   └── research/     benchmarking notes
├── gis/
│   ├── src/          DEM/terrain pipeline, exposure engine, spatial storage
│   ├── viewer/       standalone 2D/3D corridor viewer (open index.html directly)
│   └── ENGINEERING_LOG.md   dated decision log for the GIS workstream
├── data/
│   ├── ml/           trained model, historical events, metrics
│   └── gis/          DEM, terrain derivatives, spatial risk, vectors, exports
├── docs/             API contract, offline design, GIS evaluation, report reference
│   └── reference/    source material carried over from the contributing repos
├── reports/          generated report documents
└── docker-compose.yml
```

Nothing is duplicated: the backend reads the originals in `data/`, so retraining
the model or re-running the GIS pipeline updates the console with no copy step.

`ml/streaming_api/` is the original real-time telemetry service, preserved and
runnable standalone. Two of its components were adopted into the backend rather
than run as a second process — `stream_bus.py` (now the backend's fan-out layer)
and its trained-classifier inference (now `backend/app/core/ml_model.py`). Its
simulator and health monitor were deliberately *not* adopted: the backend has its
own fleet seeded against real NER districts and wired to the alert engine, and
running both would produce two authoritative timelines for the same sensors. See
`ml/streaming_api/README.md`.

---

## 3. Prerequisites

- **Python 3.11 – 3.14**
- **Node.js 18+**
- No database server, no tile server, no network. SQLite and server-rendered SVG.

`requirements.txt` uses version *floors*, not exact pins, so a newer interpreter can
pick up a wheel that supports it. If you need byte-identical installs across
machines, generate a lock file instead of re-pinning by hand:

```bash
pip install pip-tools && pip-compile requirements.txt -o requirements.lock
```

**Windows note.** If `pip install` starts compiling Rust (`maturin`, `pyo3`,
`Building wheel for pydantic-core`), you have a dependency version older than your
Python. That means a stale `requirements.txt` — stop the build and check you are on
the current one. Nothing in this project needs a compiler.

---

## 4. Running it

### Backend

```bash
cd backend      # NOT the repository root — package.json and requirements.txt live in
                # frontend/ and backend/ respectively
pip install -r requirements.txt
cp .env.example .env            # every value has a working default
python -m app.seed              # districts, zones, sensors, history, rules
uvicorn app.main:app --reload --port 8000
```

API docs at `http://localhost:8000/docs`, health at `/api/health`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env            # dev server proxies /api to :8000
npm run dev                     # http://localhost:5173
```

Production build: `npm run build` → `dist/`.

### Everything at once

```bash
docker compose up --build
```

---

## 5. Environment variables

Full lists with comments are in `backend/.env.example` and `frontend/.env.example`.
The ones that change behaviour most:

| Variable | Default | Effect |
|---|---|---|
| `SIMULATOR_ENABLED` | `true` | Drives the fleet. Set `false` when real gateways POST to `/api/ingest/readings` |
| `SIMULATOR_TICK_SECONDS` | `20` | Wall-clock seconds between telemetry ticks |
| `SIMULATOR_MINUTES_PER_TICK` | `15` | Simulated minutes advanced per tick |
| `DISPATCH_CUTOFF` | `60` | Risk score at which R1 fires |
| `TIER_RED` / `ORANGE` / `YELLOW` | `86` / `66` / `41` | Who gets told (NDMA/GSI table) |
| `RISK_BAND_*` | `80` / `60` / `35` | What colour the map is — deliberately *not* the tiers |
| `MODEL_PUBLISH_TTL_MIN` | `60` | How long an externally published prediction stays authoritative |
| `DATA_CONFIDENCE` | `SYNTHETIC` | Provenance label surfaced everywhere |
| `VITE_API_BASE_URL` | `/api` | Backend origin for the console |

Risk bands and alert tiers are separate numbers on purpose. The bands answer "how
bad does this look on screen"; the tiers answer "who gets woken up". Keeping them
apart is what lets you raise the SMS cut-off without recolouring every zone.

---

## 6. How to use it

### Sensor simulation

**Sensor Network → Sensor scenarios.** Pick a scenario and a district:

| Scenario | What it does |
|---|---|
| Normal | Baseline monsoon conditions, intermittent light rain |
| Heavy rainfall | Rain gauges climb → soil moisture → triggering index → risk → R3/R2 fire |
| Saturated slope | Ground already at field capacity → pore pressure → R4 fires |
| Slope movement | Tilt and extension accumulate → R5 fires at CRITICAL |
| Sensor failure | Part of the fleet goes silent → health falls → R7 operational alert |

A scenario perturbs the **inputs** and lets the engines reach their own
conclusions. It never writes an alert. If an alert appears the chain works; if it
does not, the chain is broken and the demonstration has said so.

The numbers move for physical reasons: rainfall raises soil moisture, which raises
pore pressure, which lowers the factor of safety, which raises risk — in that order
and with the right lags.

### Custom alert rules

**Custom Rules.** Build a rule from the engine's own parameter vocabulary (the LSI
inputs, the TI inputs, composite outputs, movement, and sensor-quality terms),
choose an operator and threshold, scope it to a district, and test it against live
conditions before saving.

Severity defaults to **automatic**, which maps the score through the four-tier
table from the methodology note:

| Score | Tier | Status | Recipients |
|---|---|---|---|
| 0–40 | Green | No warning | No message sent |
| 41–65 | Yellow | Watch | District Magistrate, SDRF |
| 66–85 | Orange | Alert | Authorities + local ward members |
| 86–100 | Red | Action | General public, geo-fenced broadcast |

So a custom rule cannot trigger a public broadcast on a score the methodology
treats as a Green day. Rules evaluate **server-side** on every cycle — a threshold
living in a browser tab stops existing when the tab closes and never fires at 03:00.

Rules marked *dashboard-only* fire and are recorded but send no messages.

### Field reports

**Field Reports.** Incident type, GPS (with district-centroid fallback if permission
is denied), road or village, severity, description, photo or video.

Submission is idempotent by client key: a device unsure whether its last attempt
landed can resend, and the server returns the original record rather than creating
a second incident for the same landslide. A failed upload goes into a device queue
in `localStorage` and retries on reconnect.

Verification is load-bearing, not bookkeeping — **rule R6 only fires on VERIFIED
reports**, so an anonymous photo can never trigger a public evacuation SMS.

### Reports

**Reports & Analytics.** Select an area, then *Generate report*. The document is
built from that area's own records: risk history, alerts, sensor performance,
recorded events, exposure and historical context. Selecting a different district
produces different figures throughout.

Ten pages: cover, executive summary, risk calendar, rainfall vs risk, spatial risk,
infrastructure exposure, sensor performance, model performance, districts and
critical events, methodology and KPI definitions. **There is no recommendations
section** — the report states what happened; deciding what to do is the district
administration's job.

Charts are server-rendered inline SVG with no CDN and no JavaScript, so the
document opens on a machine with no network. Print to PDF from the browser.

---

### Trained-model inference

The platform prefers the classifier where it is more alarmed than the rules:

```bash
cd backend
pip install -r requirements.txt -r requirements-ml.txt   # optional extras
```

Then `GET /api/model/status` reports whether it loaded, and `POST /api/model/score`
runs inference over every zone immediately. Inference otherwise runs automatically
inside each risk cycle.

**These extras are optional by design.** Without scikit-learn, joblib and pandas the
console scores every zone with the rule engine — which encodes the failure physics
and is a complete early-warning system on its own. A district office that cannot
install a 90 MB scientific stack still gets a working platform.

Where the rule engine is *more* alarmed than the model, the rules win. The
classifier sees five observable features; the rules see measured slope movement, a
verified road blockage, soil at saturation. Taking the more severe of two
independent assessments is the correct bias for early warning — a disagreement
between the statistical and the mechanical view is a reason to warn, not to average.
Both numbers are stored (`risk_score` and `model_probability`), because the
disagreement is itself a signal.

An externally published prediction (`POST /api/model/predict`) stays authoritative
for `MODEL_PUBLISH_TTL_MIN` minutes and is not overwritten by either local engine.
The window is bounded so a dead publishing pipeline cannot leave a stale score on
the console presenting itself as current.

### Standalone GIS viewer

`gis/viewer/index.html` opens directly in a browser with no build and no server. It
is the GIS workstream's digital-twin view of the Kohima–Dimapur corridor with the
payload baked in, useful for inspecting the terrain and exposure modelling on its
own. It is a frozen snapshot — it cannot show a live alert or a current sensor
reading; the console does that. Three.js and Leaflet load from CDNs, so the 3D view
needs a connection.

### Live streaming

Two transports over one bus, so they cannot show different timelines:

```bash
curl -N "http://localhost:8000/api/stream?events=zone_alert&zones=nl-kohima-z1"
```

| Transport | Endpoint | Use when |
|---|---|---|
| Server-Sent Events | `GET /api/stream` | A browser dashboard — one long-lived connection, automatic reconnection, no client library |
| WebSocket | `WS /api/ws` | The client changes its subscription while connected |

Filters (`events`, `zones`, `sensors`, `sensor_types`) are comma-separated and
applied **at publish time**, so a client watching one district never receives the
rest of the region. Every event carries a monotonic `seq`; if a client falls behind,
the bus drops that subscriber's *oldest* queued event rather than stalling the
producer or disconnecting it, and the `seq` gap is how the client knows to refill
from the REST history endpoints. `GET /api/stream/status` reports drop counters.

## 7. API overview

Base `http://localhost:8000`, snake_case, `?case=camel` for camelCase.
Full contract in `docs/API_CONTRACT.md`.

| Group | Endpoints |
|---|---|
| Risk | `/api/risk/zones`, `/zones/{id}/explain`, `/summary`, `/trend`, `/pipeline` |
| Alerts | `/api/alerts`, `/{id}/timeline`, `/acknowledge`, `/dispatch`, `/resolve`, `/delivery/*` |
| Custom rules | `/api/alerts/custom` (CRUD), `/catalogue`, `/preview`, `/{id}/alerts`, `/evaluate` |
| Sensors | `/api/sensors`, `/summary`, `/{id}/readings` |
| Simulation | `/api/simulation/scenarios`, `/state`, `/apply`, `/tick`, `/reset` |
| GIS | `/api/gis/layers`, `/layers/{id}`, `/corridor`, `/exposure`, `/context`, `/terrain` |
| Incidents | `/api/incidents`, `/api/reports/field` (GET/POST/PATCH) |
| Reports | `/api/reports/quarterly`, `/generate`, `/render`, `/files/{name}` |
| Model | `/api/model/status`, `/api/model/score`, `/api/model/predict`, `/api/model/performance` |
| Streaming | `/api/stream` (SSE), `/api/stream/status`, `/api/ws` (WebSocket) |
| Ingest | `/api/ingest/readings`, `/api/engine/run` |
| Sync | `/api/sync/bundle`, `/delta`, `/batch`, `/status` |

---

## 8. Testing

```bash
cd backend && python -m pytest tests/ -q      # 83 tests
cd frontend && npm run build                  # tsc -b && vite build
```

Verified end to end: risk summary and pipeline; nine GIS layers with no DEM toggle;
sensor telemetry with health, battery and status; heavy rainfall propagating to a
new alert; custom rule create → preview → evaluate → related alerts → delete with
alerts retained; field report → idempotent resubmit → verification → GIS map → R6;
reports differing by district with no recommendations, rendering 10 pages of
inline-SVG charts.

---

## 9. Data provenance

| Label | What it means | Source |
|---|---|---|
| **Simulated** | Sensor telemetry from the physics-informed fleet simulator. Not a field measurement. | `backend/app/core/telemetry.py` |
| **Historical** | Recorded regional landslide events, 2015–2025, at **state** resolution. | `data/ml/historical_events_cleaned.csv` |
| **Model-derived** | Risk scores, probabilities, exposure rankings. | risk engine, `data/ml/risk_model.joblib` |
| **GIS** | DEM, seven terrain derivatives, spatial risk surface, corridor vectors. | `data/gis/` |
| **User-reported** | Field and citizen reports. A signal, acted on only once verified. | `/api/reports/field` |

The historical dataset is reported at state level because that is the resolution it
has — every row carries a state and a coordinate but no district. Presenting it as a
district figure would invent precision the source does not contain.

---

## 10. Known limitations

- **No real sensor hardware.** Telemetry is simulated. The ingest path
  (`/api/ingest/readings`) is real and idempotent, so a LoRa/GSM gateway replaces the
  simulator without touching anything downstream.
- **No live weather feed.** `IMD_API_BASE` is unset; weather is simulator-derived.
  Requires an IMD API credential.
- **No SMS gateway.** `SMS_PROVIDER=console` logs messages. `http` and
  `store_forward` providers exist and need a gateway endpoint and key.
- **The historical dataset is synthesised**, not observed. The loaders and field
  mappings for GSI Bhukosh and NASA COOLR exist in `ml/data_pipeline/`.
- **Model metrics are measured against simulated scenarios**, not field outcomes.
  Treat ROC AUC 0.786 as a pipeline baseline.
- **The shipped model artefact was pickled under a different scikit-learn** than
  current releases load it with. It loads and predicts, but scikit-learn does not
  guarantee cross-version unpickling. `GET /api/model/status` surfaces this as a
  warning; clear it by retraining: `python ml/pipeline/train_risk_model.py`.
- **The standalone streaming service and the backend both simulate a fleet.** Run
  one or the other, not both against the same dashboard, or you get two
  authoritative timelines for the same sensors.
- **Corridor GIS covers one alignment** (Kohima–Dimapur NH-29, 100×100 at 10 m).
  Elsewhere spatial risk falls back to zone polygons.
- **An alert's headline trigger is historical, its contributing rules are current.**
  If R5 fired at CRITICAL an hour ago and only R1/R3 match now, the alert still reads
  R5 (it is not re-labelled downward on the same open alert) while
  `contributing_rules` shows what matched on the latest cycle. This is deliberate —
  an authority tracking an alert should not see its stated reason change under them —
  but the two fields answer different questions and should be read that way.
- **Auth is off by default** (`AUTH_ENABLED=false`). Role boundaries are enforced in
  one place, so adding a real identity provider is a swap of `current_user`.
- **Single-process simulation state.** The scenario in effect lives in memory; a
  backend restart returns the fleet to Normal.
- **Verified on Python 3.12 and 3.14, Node 20.** Other versions inside the supported
  ranges should work but were not exercised.
