# NER Landslide Early Warning System — Backend

Backend, risk engine, alert engine and offline sync for **SIH PS 26001 — AI-Based
Early Warning and Landslide Risk Monitoring System in the North Eastern Region**
(Ministry of Development of North Eastern Region).

Owner: **Krish Modi** — backend, integration, alert engine, offline architecture.

> **Demo build.** Every district, zone, sensor, reading, alert and report served by
> this API is synthetic and labelled `data_confidence: "SYNTHETIC"` in the payload
> and in the `X-Data-Confidence` response header. This service has no authority to
> issue an official warning.

---

## Running it

```bash
./run.sh                 # venv + install + seed + serve on :8000
RESEED=1 ./run.sh        # wipe and reseed first
```

Or by hand:

```bash
pip install -r requirements.txt
python -m app.seed       # 30 districts, 67 zones, 267 sensors, 6.4k readings
uvicorn app.main:app --reload --port 8000
```

- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>
- Tests: `pytest -q` (60 tests)

Requires Python 3.11+. SQLite by default — no services to install. Point
`DATABASE_URL` at Postgres/PostGIS for deployment; nothing in the models is
SQLite-specific.

---

## What this service is

```
sensors ─┐
rainfall ─┼─→ ingest ─→ sensor health ─→ RISK ENGINE ─→ ALERT ENGINE ─→ delivery
terrain  ─┘                  (Eisa)      (LSI × TI)      (7 rules)     (SMS/push)
                                              ↑                ↓
                                     ML model override    audit trail
                                        (Saksham)          + dispatch ledger
                                              ↓
                              REST API ─→ console (Akshita) / GIS (Ayush) / reports (Nitin)
                                   ↕
                            offline sync (bundle / batch / delta)
```

56 endpoints. Every route in `INTEGRATION.md` is implemented, plus the ingest,
sync, explainability and audit endpoints the platform needs but the frontend
contract did not yet name.

---

## Structure

```
app/
├── config.py              Every tunable threshold, all env-overridable
├── db.py                  Engine + session
├── models.py              22 tables. snake_case columns == wire contract
├── serializers.py         ORM → wire. One function per DTO
├── casing.py              snake_case ⇄ camelCase at the edge (?case=camel)
├── deps.py                Scope filter, response shaping, roles
├── services.py            run_risk_cycle() + read-side aggregation
├── seed.py                Deterministic seeding
├── core/
│   ├── risk_engine.py     LSI/TI methodology → risk_score, level, tier
│   ├── sensor_health.py   5-factor health score (Eisa's weights)
│   ├── alert_engine.py    7 rules, dedup, escalation, lifecycle
│   └── notify.py          Tier→audience routing, multilingual SMS, retry ledger
├── data/regions.py        8 states, 30 districts — IDs match the frontend exactly
└── routers/               risk, alerts, sensors, gis, incidents, reports,
                           platform, sync, ingest
```

---

## The three engines

### 1. Risk (`core/risk_engine.py`)

Direct implementation of the team's methodology note:

```
LSI  = slope 40% + soil 25% + landcover 20% + elevation/aspect 15%
TI   = soil moisture 30% + rain24h 30% + rain72h 15% + rain7d 10% + API 15%
risk = (LSI × 0.4 + TI × 0.6) × 100
```

Non-obvious behaviours that are correct and should not be "fixed":

- **Slope score dips above 45°.** Very steep faces are usually exposed bedrock,
  which fails less often than a soil mantle. The peak is 30–45°.
- **Aspect penalises SW-facing slopes** (cosine about 225°) — the southwest
  monsoon's direct line.
- **Sensor confidence never lowers the risk score.** A slope does not become safer
  because a battery died. Confidence travels alongside the score so the alert
  engine can route a low-confidence warning to a human instead of silently
  downgrading it. There is a test for this.

`GET /api/risk/zones/{id}/explain` returns the full breakdown. An early-warning
system that cannot justify a warning will not get one acted on — a DM being asked
to close a highway is entitled to see which factor drove the number.

### 2. Alerts (`core/alert_engine.py`)

Seven rules run per zone per cycle:

| Rule | Trigger | Fires when |
|---|---|---|
| R1 | `MODEL_PROBABILITY` | risk ≥ dispatch cut-off |
| R2 | `COMBINED` | soil ≥ 70% **and** rain ≥ 0.7 × district threshold |
| R3 | `RAINFALL_THRESHOLD` | 24 h rainfall ≥ district threshold |
| R4 | `SOIL_SATURATION` | soil moisture ≥ 80% |
| R5 | `SLOPE_MOVEMENT` | tilt/extensometer drift over 3 intervals |
| R6 | `ROAD_BLOCKAGE` | **verified** field report, last 12 h |
| R7 | `SENSOR_ANOMALY` | ≥ 50% of a zone's sensors offline |

**R2 is the one that matters here.** NER slopes fail when the ground is already
saturated and a fresh burst arrives. Neither input alone would fire — which is
exactly why single-variable rainfall warnings miss events in this region.

**R7 is not a landslide warning.** It says we have lost the ability to make one for
that zone, which during a monsoon is its own emergency.

Three mechanisms turn scores into messages without destroying trust:

- **Dedup per (zone, class)** — one hillside produces one hazard alert regardless of
  how many rules fire. `OPERATIONAL` (R7) is a separate class so a sensor outage can
  never overwrite a landslide warning on the same slope.
- **Escalation in place** — worsening conditions raise severity and re-dispatch, but
  the alert **ID does not change**, so an authority tracking `ALT-1004` keeps
  tracking `ALT-1004`.
- **Re-arm window** — after RESOLVED, recreation is held off for the cooldown.
  Without it, resolving an alert on a still-wet slope instantly spawns a replacement
  and the console fights the operator.

Lifecycle `NEW → ACKNOWLEDGED → IN_PROGRESS → RESOLVED` is enforced in
`transition()`; illegal jumps return **409**, they do not silently corrupt state.
Every transition is written to `alert_events`.

### 3. Delivery (`core/notify.py`)

Audience is a function of **tier**, not severity:

| Tier | Score | Audience | Meaning |
|---|---|---|---|
| 🟢 GREEN | < 41 | nobody | Normal conditions |
| 🟡 YELLOW | 41–65 | DM, SDRF | Watch — saturated soil |
| 🟠 ORANGE | 66–85 | + ward members | Alert — threshold crossed |
| 🔴 RED | ≥ 86 | + public broadcast | Action — imminent failure |

Sending every alert to everyone is how a warning system trains a district to ignore
it. Two safeguards:

- A **low-confidence** alert never reaches `PUBLIC` unverified — the instruments we
  would be asking people to trust are the ones already known to be unreliable.
- Templates are per-language and **lead with the action**, not the score. Nobody
  evacuates because of "risk score 87". Messages are kept under 160 GSM-7 characters
  where possible: three parts arrive out of order on a congested rural cell and read
  as gibberish.

Providers: `console` (demo), `http` (gateway), `store_forward` (satellite/LoRa —
marks deferred rather than failed, drains when the link returns). Every attempt is a
row in `dispatches` with attempt count and last error.

---

## Risk bands vs alert tiers — read this before presenting

The frontend README bands risk at **≥80 / 60 / 35**. The methodology note bands at
**0.86 / 0.66 / 0.41**. These are different numbers and I did not pick one.

- **Risk bands** drive what the console *displays* (`risk_level`).
- **Alert tiers** drive *who gets an SMS* (`alert_tier`).

Both are editable at `GET/PATCH /api/settings/thresholds`. Changing who gets woken at
3 a.m. should not repaint the map. If a judge asks, that separation is a stronger
answer than either number alone.

---

## Data honesty

- `data_confidence: "SYNTHETIC"` on every payload; `X-Data-Confidence` on every
  response.
- The DEM grid is procedural and labelled `SYNTHETIC_DEM` with a note naming its
  replacement (CartoDEM/Bhuvan).
- Model metrics (ROC-AUC 0.786, recall 0.850, precision 0.549) ship with their
  **caveat text stored in the database**, not just rendered in the UI. Those numbers
  came from ~8,000 physics-simulated scenarios, not field outcomes. A judge who
  discovers that themselves will discount everything else — say it first.
- GIS layers with no data source return **409 with a reason**, not 404 and not an
  empty array, so the UI can render a disabled toggle explaining why.

---

## Known limitations

1. **Report generation returns a job handle but no renderer.** `POST
   /api/reports/generate` queues a job; nothing processes the queue yet. The console
   already handles the pending state.
2. **Auth is minimal and off by default.** HMAC-signed tokens, four roles, enforced
   in one place (`deps.require_role`). Real deployment needs the state's SSO — the
   swap point is `current_user`, not an audit of every endpoint.
3. **WebSocket fan-out is in-process.** Fine at district scale; needs a broker to
   run more than one worker. Swap point is `Hub.broadcast`.
4. **IMD pull is configured, not implemented.** `IMD_API_BASE` is respected and the
   endpoint reports `NOT_CONFIGURED` honestly rather than pretending.
5. **No rate limiting** on the public field-report endpoint. Needed before any real
   citizen-facing deployment.
6. **Media is stored on local disk.** Move to S3/MinIO for a multi-node deployment.

See `API_CONTRACT.md` for the full endpoint reference and
`OFFLINE_AND_DELIVERY.md` for the offline architecture and warning-delivery research.
