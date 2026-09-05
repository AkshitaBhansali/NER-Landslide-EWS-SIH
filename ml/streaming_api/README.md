# Real-Time Sensor Streaming API

> **Where this sits in the integrated platform.** This service is preserved intact
> and still runs standalone (`cd ml && python -m streaming_api`). Two of its ideas
> were adopted into the platform backend rather than run as a second process:
>
> * `stream_bus.py` is now also the backend's fan-out layer, giving `/api/stream`
>   (SSE) and `/api/ws` per-subscriber filtering, monotonic `seq` and a
>   drop-oldest backpressure policy.
> * The trained-classifier inference this service pioneered now runs in the
>   backend's risk cycle (`backend/app/core/ml_model.py`), sharing the same
>   `risk_output_schema()` contract so the two paths cannot drift.
>
> Its simulator and health monitor were *not* adopted: the backend has its own
> fleet, seeded against real NER districts and wired to the alert engine. Running
> both would produce two authoritative timelines for the same sensors.


Serves live sensor telemetry, sensor health and zone risk for the NER landslide
early warning platform over REST, Server-Sent Events and WebSocket.

## Contents

1. [Quick start](#quick-start)
2. [What the service produces](#what-the-service-produces)
3. [Architecture](#architecture)
4. [Streaming transports](#streaming-transports)
5. [Event catalogue](#event-catalogue)
6. [Endpoint reference](#endpoint-reference)
7. [Client examples](#client-examples)
8. [Configuration](#configuration)
9. [Simulated fleet](#simulated-fleet)
10. [Backpressure and delivery guarantees](#backpressure-and-delivery-guarantees)
11. [Verification](#verification)
12. [Replacing the simulator with real hardware](#replacing-the-simulator-with-real-hardware)
13. [Limitations](#limitations)

## Quick start

```bash
cd ml
pip install -r streaming_api/requirements.txt
python -m streaming_api
```

The service starts on `http://127.0.0.1:8000`.

| Address | Purpose |
|---|---|
| `http://127.0.0.1:8000/docs` | Interactive OpenAPI documentation |
| `http://127.0.0.1:8000/dashboard` | Built-in stream viewer |
| `http://127.0.0.1:8000/api/v1/stream` | Server-Sent Events feed |
| `ws://127.0.0.1:8000/api/v1/ws` | WebSocket feed |

Follow the raw stream from a terminal:

```bash
curl -N http://127.0.0.1:8000/api/v1/stream
```

Startup runs a seven-day simulated warm-up before the first request is served,
so rainfall accumulations, saturation state and reading buffers are already
populated rather than starting from zero. Warm-up takes a few seconds.

## What the service produces

Readings conform exactly to `SENSOR_READING_SCHEMA` in
`data_pipeline/schema.py`, which is the same contract the offline pipeline
consumes:

```json
{
  "sensor_id": "NER-Z03-PZ-01",
  "zone_id": "NER-Z03",
  "sensor_type": "piezometer",
  "timestamp": "2026-08-31T13:40:00+00:00",
  "value": 7.8412,
  "unit": "kPa",
  "battery_pct": 88.4,
  "rssi_dbm": -64.2,
  "expected_interval_s": 300
}
```

Alongside the raw feed the service publishes derived state: a 0 to 100 health
score per sensor, and a risk record per zone carrying the platform output
contract (`risk_score`, `risk_level`, `probability`, `contributing_factors`).

## Architecture

```
simulator.py       physical state per zone, sensor readings per tick
      |
runtime.py         the single tick task: advance, publish, assess, score
      |            |                    |
      |            |                    +-- risk_engine.py     trained model plus Factor of Safety
      |            +----------------------- health_monitor.py  stream cleaning and health scoring
      |
stream_bus.py      per-subscriber queues, filtering, backpressure
      |
service.py         REST, Server-Sent Events, WebSocket, simulation controls
```

One background task owns the simulation. HTTP and WebSocket handlers never
advance it; they read the state it maintains. This keeps a single authoritative
timeline no matter how many clients are connected, and means adding a client
costs a queue rather than a simulation.

The risk engine calls `risk_output_schema()` from `ml/train_risk_model.py`
directly, so the live path and the offline path cannot drift apart. If
`data/risk_model.joblib` is absent the engine falls back to deriving risk from
the Factor of Safety and reports `"source": "physics_fallback"`, so the service
still streams before the training script has been run.

## Streaming transports

| Transport | Endpoint | Use it when |
|---|---|---|
| Server-Sent Events | `GET /api/v1/stream` | The client is a browser dashboard. One long-lived connection, automatic reconnection, no client library |
| WebSocket | `WS /api/v1/ws` | The client needs to change its subscription while connected, for example a map that re-subscribes on zone selection |
| REST | `GET /api/v1/...` | Page load, clients that cannot hold a connection open, and recovering readings missed during a disconnection |

All three serve the same state.

Every streamed event carries the same envelope:

```json
{
  "seq": 4211,
  "event": "sensor_reading",
  "emitted_at": "2026-08-31T13:40:00+00:00",
  "data": { }
}
```

`seq` is monotonic, so a client can detect events lost to backpressure and
refill from `GET /api/v1/sensors/{sensor_id}/readings`.

### Filtering

Both streaming endpoints accept the same filters as comma-separated query
parameters. Filtering is applied at publish time, so a client subscribed to one
zone never receives the rest of the fleet.

| Parameter | Example |
|---|---|
| `events` | `events=sensor_reading,zone_alert` |
| `zones` | `zones=NER-Z03,NER-Z06` |
| `sensors` | `sensors=NER-Z03-PZ-01` |
| `sensor_types` | `sensor_types=piezometer,tiltmeter` |
| `snapshot` | `snapshot=true` sends a full state snapshot before the live events (Server-Sent Events only) |

## Event catalogue

| Event | Published | Payload |
|---|---|---|
| `sensor_reading` | Once per sensor per tick | `SENSOR_READING_SCHEMA` |
| `zone_risk` | On the risk refresh cadence | Risk record: score, level, probability, contributing factors, Factor of Safety, observations, sensor confidence |
| `zone_alert` | Only when a zone's alert level rises | Alert record with the previous and new level and the triggering conditions |
| `sensor_health` | On the health refresh cadence | Fleet health summary with the status distribution |
| `sensor_fault` | When a simulated instrument fault begins | Sensor, fault type and expected duration |
| `tick` | Every tick | Simulated clock, reading count, fault count, subscriber count |

An alert is raised on escalation rather than on every assessment, so
`GET /api/v1/alerts` is an escalation history rather than a poll log.

## Endpoint reference

### Service

| Method | Path | Returns |
|---|---|---|
| `GET` | `/` | Service index and endpoint map |
| `GET` | `/health` | Liveness, simulated clock, tick count, model in use, health summary |
| `GET` | `/api/v1/schema` | Canonical reading schema, event catalogue, envelope description, fault types |
| `GET` | `/docs` | Interactive OpenAPI documentation |
| `GET` | `/dashboard` | Built-in stream viewer |

### Zones and sensors

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/v1/zones` | All zones with descriptors and live conditions |
| `GET` | `/api/v1/zones/{zone_id}` | One zone with conditions, current risk and sensor roster |
| `GET` | `/api/v1/sensors` | Fleet listing with latest reading and health status. Filters: `zone_id`, `sensor_type` |
| `GET` | `/api/v1/sensors/{sensor_id}` | One sensor with descriptor, latest reading and full health record |
| `GET` | `/api/v1/sensors/{sensor_id}/readings` | Buffered readings, oldest first. Filters: `limit`, `since` |

### Health and risk

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/v1/sensors/{sensor_id}/health` | Composite score, five sub-scores, maintenance notes |
| `GET` | `/api/v1/fleet/health` | Health for the whole fleet or one zone. Filter: `zone_id` |
| `GET` | `/api/v1/risk` | Current risk record for every zone |
| `GET` | `/api/v1/risk/{zone_id}` | Current risk record for one zone |
| `GET` | `/api/v1/alerts` | Escalation history, newest first. Filter: `limit` |
| `GET` | `/api/v1/snapshot` | Complete point-in-time state. Filter: `zone_id` |

### Streaming

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/v1/stream` | Server-Sent Events feed |
| `WS` | `/api/v1/ws` | WebSocket feed |
| `GET` | `/api/v1/stream/stats` | Publisher and per-connection subscriber statistics including drop counts |

### Simulation controls

These exist because waiting for the stochastic rainfall process to produce a
storm makes the alerting path impractical to demonstrate or test. Injected
conditions feed the normal accumulation and saturation path, so the resulting
alert is produced by the same code that would handle real rainfall.

| Method | Path | Body |
|---|---|---|
| `POST` | `/api/v1/simulation/rainfall-surge` | `{"zone_id": "NER-Z03", "rate_mm_hr": 90, "duration_minutes": 2880}` |
| `POST` | `/api/v1/simulation/sensor-fault` | `{"sensor_id": "NER-Z03-PZ-01", "fault": "comms_dropout", "duration_ticks": 20}` |
| `POST` | `/api/v1/simulation/clear` | No body. Clears every active fault and surge |

Valid fault types are `comms_dropout`, `stuck_reading`, `calibration_drift` and
`noise_burst`.

## Client examples

### Browser, Server-Sent Events

```javascript
const source = new EventSource('/api/v1/stream?zones=NER-Z03&snapshot=true');

source.addEventListener('snapshot', e => renderAll(JSON.parse(e.data)));
source.addEventListener('sensor_reading', e => updateSensor(JSON.parse(e.data).data));
source.addEventListener('zone_alert', e => raiseAlert(JSON.parse(e.data).data));
```

### Browser, WebSocket with a changing subscription

```javascript
const socket = new WebSocket('ws://127.0.0.1:8000/api/v1/ws');

socket.onmessage = e => handle(JSON.parse(e.data));

function selectZone(zoneId) {
  socket.send(JSON.stringify({
    action: 'subscribe',
    events: ['sensor_reading', 'zone_risk', 'zone_alert'],
    zones: [zoneId],
  }));
}
```

Accepted WebSocket actions are `subscribe`, `snapshot` and `ping`.

### Python

```python
import json
import httpx

with httpx.Client(timeout=None) as client:
    with client.stream("GET", "http://127.0.0.1:8000/api/v1/stream",
                       params={"events": "zone_alert"}) as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                print(json.loads(line[5:]))
```

## Configuration

Every setting is an environment variable prefixed with `NER_EWS_`.

| Variable | Default | Effect |
|---|---|---|
| `NER_EWS_HOST` | `127.0.0.1` | Bind address |
| `NER_EWS_PORT` | `8000` | Bind port |
| `NER_EWS_SIM_STEP_S` | `300` | Simulated seconds advanced per tick, and the reporting cadence written to `expected_interval_s` |
| `NER_EWS_TICK_INTERVAL_S` | `2.0` | Real seconds between ticks |
| `NER_EWS_SEED` | `42` | Simulator seed |
| `NER_EWS_WARMUP_DAYS` | `7.0` | Simulated days run before the service accepts traffic |
| `NER_EWS_HISTORY_READINGS` | `288` | Readings buffered per sensor |
| `NER_EWS_FAULT_INJECTION` | `true` | Whether random instrument faults occur |
| `NER_EWS_RISK_REFRESH_TICKS` | `1` | Ticks between zone risk reassessments |
| `NER_EWS_HEALTH_REFRESH_TICKS` | `12` | Ticks between fleet health rescores |
| `NER_EWS_SUBSCRIBER_QUEUE_SIZE` | `512` | Events buffered per connected client |
| `NER_EWS_MAX_SUBSCRIBERS` | `64` | Concurrent stream connections |
| `NER_EWS_HEARTBEAT_S` | `15.0` | Seconds of silence before a keepalive comment is sent |
| `NER_EWS_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `NER_EWS_MODEL_DIR` | `data/` | Directory holding `risk_model.joblib` and `feature_importance.csv` |

### Clock model

The service keeps a simulated clock separate from wall-clock time. Each tick
advances the simulated clock by `SIM_STEP_S` and then sleeps `TICK_INTERVAL_S`
of real time, giving a time acceleration of `SIM_STEP_S / TICK_INTERVAL_S`. The
defaults deliver a five-minute sensor cadence every two seconds, which is 150
times real time and makes a multi-day rainfall event observable in minutes.

Set `NER_EWS_TICK_INTERVAL_S=300` for real-time operation. Readings always
carry `expected_interval_s = SIM_STEP_S`, so gap and communication-failure
detection stays correct at any acceleration. `GET /health` reports the
acceleration in use.

## Simulated fleet

Six instrumented corridors, each with a documented history of
rainfall-triggered slope failure affecting a lifeline road, rail line or urban
settlement.

| Zone | Corridor | State | Slope | Rainfall intensity |
|---|---|---|---|---|
| `NER-Z01` | NH-10 Teesta Corridor | Sikkim | 34 degrees | 1.15 |
| `NER-Z02` | Sohra Plateau Escarpment | Meghalaya | 30 degrees | 1.85 |
| `NER-Z03` | Aizawl Urban Slopes | Mizoram | 33 degrees | 1.10 |
| `NER-Z04` | Haflong Hill Rail Section | Assam | 27 degrees | 1.25 |
| `NER-Z05` | Itanagar Capital Approach | Arunachal Pradesh | 29 degrees | 1.30 |
| `NER-Z06` | Tupul Rail Embankment | Manipur | 32 degrees | 1.20 |

Each zone carries seven instruments, for 42 sensors in total: one rain gauge,
two soil moisture probes at different depths, one piezometer, one tiltmeter,
one extensometer and one geophone.

Readings are not random noise. A rainfall burst propagates through soil
moisture, then pore pressure, then deformation, then risk score, in the correct
physical order and with the correct lags, because every sensor reads off the
same zone state that the Factor of Safety is computed from. Zone parameters are
set so that each slope is comfortably stable when dry (Factor of Safety 1.30 to
1.75) and reaches or approaches failure when the slip surface saturates (0.77
to 0.99). Rainfall is generated by a four-state Markov chain with monsoon
seasonality, calibrated to roughly 25 mm per day through the monsoon for a zone
of intensity 1.0, with a 24-hour 99th percentile near 110 mm.

Instrument faults are injected at low probability: communication dropouts,
stuck readings, calibration drift and noise bursts, along with gradual battery
discharge and rainfall-dependent signal attenuation. A stream in which nothing
ever fails cannot exercise the quality-control path, so the health scores the
API serves move for real reasons.

## Backpressure and delivery guarantees

Each subscriber holds a bounded queue. When a client reads more slowly than the
service publishes, the oldest event in that client's queue is discarded to make
room for the newest and the connection's `dropped` counter is incremented. One
slow client cannot stall the simulator or any other client.

Dropping the oldest is the right policy here: for an early warning stream the
newest reading is always the more useful one, and the client can detect the
loss through the `seq` gap and refill the exact readings from
`GET /api/v1/sensors/{sensor_id}/readings`. Per-connection drop counts are
visible at `GET /api/v1/stream/stats`.

Delivery is therefore at-most-once on the stream, with an exact replay path
over REST for anything missed within the buffer window.

## Verification

```bash
python -m api.smoke_test
```

Starts the service on a spare port and exercises every endpoint, both
streaming transports, the filtering behaviour, the simulation controls and the
alerting path, then prints a pass or fail line per check. It runs against a
real server process rather than an in-process transport, because the properties
worth checking are the ones an in-process transport hides: that the
Server-Sent Events response streams incrementally instead of buffering to
completion, and that the WebSocket upgrade and subscription protocol work over
a real socket.

The simulator can also be run on its own:

```bash
python api/simulator.py
```

## Replacing the simulator with real hardware

`SensorFleetSimulator` stands in for the gateway that will eventually receive
readings from field hardware. Because it emits `SENSOR_READING_SCHEMA` records
and nothing downstream knows where they came from, the replacement is confined
to one module:

1. Add an ingestion endpoint or gateway consumer that accepts readings in
   `SENSOR_READING_SCHEMA`.
2. Write them into the same per-sensor buffers the simulator maintains.
3. Publish each accepted reading to the stream bus with the same routing keys.

The stream bus, health monitor, risk engine, REST layer and both streaming
transports need no change, because none of them depends on the origin of a
reading.

## Limitations

1. Readings are simulated. The physics is real and the schema is the production
   contract, but no field hardware is deployed, so nothing served here is an
   observation.
2. State is in memory only. Restarting the service resets the simulated clock,
   the reading buffers and the alert history. A production deployment needs a
   time-series store behind the ingestion path, which is also what would allow
   history requests to reach past the buffer window.
3. There is no authentication or rate limiting. Both belong at the gateway in
   front of this service rather than inside it, but neither is configured yet.
4. The service runs as a single process. The stream bus is in-process, so
   horizontal scaling requires moving fan-out to an external broker such as
   Redis publish and subscribe.
5. Drift detection in the health score is confounded by genuine hydrological
   trend. `SensorStreamCleaner.detect_drift` compares each window against the
   first window of the buffer, which is valid for a quasi-stationary signal,
   but soil moisture really does climb by twenty points during a storm. The
   live monitor raises the z-threshold to compensate and treats stability as a
   weak signal. Separating instrument drift from real trend requires comparing
   a sensor against its own modelled expectation.
6. The saturation term uses a wetting front fraction rather than the full soil
   column, unlike the committed physics dataset. This is documented in
   `research/dataset_construction.md` as a known artefact of the full-column
   formulation, and is corrected here so that rainfall moves the Factor of
   Safety by a realistic amount. The offline dataset is unchanged.
