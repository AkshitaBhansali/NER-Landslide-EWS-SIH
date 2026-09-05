"""
Streaming Service
=================

Purpose
-------
The HTTP and WebSocket surface of the platform. It exposes the live sensor
feed in three forms, because the consumers have different needs:

1. Server-Sent Events (`GET /api/v1/stream`) for the operator dashboard. One
   long-lived connection, automatic reconnection in the browser, no client
   library required.
2. WebSocket (`WS /api/v1/ws`) for clients that need to change their
   subscription while connected, such as a map that re-subscribes when the
   operator selects a different zone.
3. REST snapshots and history (`GET /api/v1/...`) for page loads, for clients
   that cannot hold a connection open, and for recovering readings missed
   during a disconnection.

All three serve the same underlying state, produced by the single tick task in
`api/runtime.py`.

Stream envelope
---------------
Every streamed event carries the same envelope:

    {"seq": 4211, "event": "sensor_reading",
     "emitted_at": "2026-08-31T13:40:00+00:00", "data": {...}}

`seq` is monotonic per connection origin, so a client can detect events lost
to backpressure and refill from the REST history endpoints. `data` for a
`sensor_reading` event is exactly `SENSOR_READING_SCHEMA`, unchanged from
`data_pipeline/schema.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import SETTINGS
from .runtime import StreamingRuntime
from .simulator import FAULT_PROFILES, SENSOR_UNITS
from .stream_bus import ALL_EVENT_TYPES, StreamEvent, Subscription

# Importing the runtime places the repository root on sys.path, which is what
# makes the canonical schema importable here.
from data_pipeline.schema import SENSOR_READING_SCHEMA   # noqa: E402

logger = logging.getLogger("ner_ews.service")

runtime = StreamingRuntime(SETTINGS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(
    title="NER Landslide EWS Sensor Stream API",
    version=__version__,
    description=(
        "Real-time sensor telemetry, sensor health and zone risk for the North "
        "Eastern Region landslide early warning platform. Readings conform to "
        "SENSOR_READING_SCHEMA in data_pipeline/schema.py."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class RainfallSurgeRequest(BaseModel):
    """Forces a zone into a heavy rainfall regime, for demonstrating the path
    from rainfall through saturation to alert without waiting for the stochastic
    rainfall process to produce a storm."""

    zone_id: str = Field(..., description="Target zone, for example NER-Z03")
    rate_mm_hr: float = Field(60.0, gt=0, le=300, description="Rainfall intensity to hold")
    duration_minutes: float = Field(720.0, gt=0, le=20160,
                                    description="Simulated duration of the surge")


class SensorFaultRequest(BaseModel):
    """Forces a named fault onto one sensor, for exercising the quality-control
    and sensor-health path."""

    sensor_id: str = Field(..., description="Target sensor, for example NER-Z03-PZ-01")
    fault: str = Field(..., description=f"One of {sorted(FAULT_PROFILES)}")
    duration_ticks: Optional[int] = Field(None, gt=0, le=5000,
                                          description="Ticks to hold the fault")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _split(value: Optional[str]) -> Optional[list]:
    if not value:
        return None
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return parts or None


def _validate_events(events: Optional[list]) -> Optional[list]:
    if events is None:
        return None
    unknown = [e for e in events if e not in ALL_EVENT_TYPES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event types {unknown}. Valid types: {list(ALL_EVENT_TYPES)}",
        )
    return events


def _require_zone(zone_id: str):
    zone = runtime.simulator.zones.get(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Unknown zone_id '{zone_id}'")
    return zone


def _require_sensor(sensor_id: str):
    sensor = runtime.simulator.sensors.get(sensor_id)
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"Unknown sensor_id '{sensor_id}'")
    return sensor


def _sse_packet(event: StreamEvent) -> str:
    return (
        f"id: {event.seq}\n"
        f"event: {event.event}\n"
        f"data: {json.dumps(event.envelope(), separators=(',', ':'))}\n\n"
    )


def _sse_inline(event_name: str, payload: dict) -> str:
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    )


# ---------------------------------------------------------------------------
# Service metadata
# ---------------------------------------------------------------------------
@app.get("/", tags=["service"])
def index() -> dict:
    """Service index with the available endpoints."""
    return {
        "service": "NER Landslide EWS Sensor Stream API",
        "version": __version__,
        "documentation": {"openapi": "/docs", "reference": "/openapi.json"},
        "dashboard": "/dashboard",
        "endpoints": {
            "status": "/health",
            "schema": "/api/v1/schema",
            "zones": "/api/v1/zones",
            "sensors": "/api/v1/sensors",
            "readings": "/api/v1/sensors/{sensor_id}/readings",
            "fleet_health": "/api/v1/fleet/health",
            "risk": "/api/v1/risk",
            "alerts": "/api/v1/alerts",
            "snapshot": "/api/v1/snapshot",
            "stream_sse": "/api/v1/stream",
            "stream_ws": "/api/v1/ws",
        },
    }


@app.get("/health", tags=["service"])
def health() -> dict:
    """Liveness and runtime status, including the simulated clock and the model
    the risk engine is serving from."""
    return runtime.status()


@app.get("/api/v1/schema", tags=["service"])
def stream_schema() -> dict:
    """The canonical reading schema and the event catalogue, so a client can be
    written against the contract rather than against observed samples."""
    return {
        "sensor_reading_schema": SENSOR_READING_SCHEMA,
        "sensor_units": SENSOR_UNITS,
        "event_types": list(ALL_EVENT_TYPES),
        "envelope": {
            "seq": "int    - monotonic sequence number, gaps indicate dropped events",
            "event": "str    - one of the event types above",
            "emitted_at": "datetime - simulated time of emission, ISO 8601",
            "data": "object - payload, schema depends on the event type",
        },
        "fault_types": sorted(FAULT_PROFILES),
    }


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
@app.get("/api/v1/zones", tags=["zones"])
def list_zones() -> dict:
    """All monitored zones with their static descriptors and live conditions."""
    return {
        "count": len(runtime.simulator.zones),
        "simulated_time": runtime.simulator.clock.isoformat(),
        "zones": [
            {**zone.descriptor(), "conditions": zone.conditions()}
            for zone in runtime.simulator.zones.values()
        ],
    }


@app.get("/api/v1/zones/{zone_id}", tags=["zones"])
def get_zone(zone_id: str) -> dict:
    """One zone with its conditions, current risk record and sensor roster."""
    zone = _require_zone(zone_id)
    return {
        **zone.descriptor(),
        "conditions": zone.conditions(),
        "risk": runtime.risk_cache.get(zone_id),
        "sensors": [s.descriptor() for s in runtime.simulator.sensors_in_zone(zone_id)],
    }


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------
@app.get("/api/v1/sensors", tags=["sensors"])
def list_sensors(
    zone_id: Optional[str] = Query(None, description="Filter by zone"),
    sensor_type: Optional[str] = Query(None, description="Filter by sensor type"),
) -> dict:
    """The sensor fleet with each unit's latest reading and health status."""
    sensors = list(runtime.simulator.sensors.values())
    if zone_id:
        _require_zone(zone_id)
        sensors = [s for s in sensors if s.zone_id == zone_id]
    if sensor_type:
        sensors = [s for s in sensors if s.sensor_type == sensor_type]

    return {
        "count": len(sensors),
        "simulated_time": runtime.simulator.clock.isoformat(),
        "sensors": [
            {
                **sensor.descriptor(),
                "latest_reading": runtime.simulator.latest_reading(sensor.sensor_id),
                "health_score": (runtime.health_monitor.sensor_health(sensor.sensor_id) or {})
                .get("health_score"),
                "health_status": (runtime.health_monitor.sensor_health(sensor.sensor_id) or {})
                .get("status"),
            }
            for sensor in sensors
        ],
    }


@app.get("/api/v1/sensors/{sensor_id}", tags=["sensors"])
def get_sensor(sensor_id: str) -> dict:
    """One sensor with its descriptor, latest reading and full health record."""
    sensor = _require_sensor(sensor_id)
    return {
        **sensor.descriptor(),
        "latest_reading": runtime.simulator.latest_reading(sensor_id),
        "health": runtime.health_monitor.sensor_health(sensor_id),
    }


@app.get("/api/v1/sensors/{sensor_id}/readings", tags=["sensors"])
def get_readings(
    sensor_id: str,
    limit: int = Query(100, ge=1, le=2000, description="Maximum readings to return"),
    since: Optional[str] = Query(None, description="Return readings at or after this ISO 8601 time"),
) -> dict:
    """Buffered readings for one sensor, oldest first.

    This is the recovery path for a client that lost events to backpressure or
    a dropped connection. The buffer holds the most recent
    `NER_EWS_HISTORY_READINGS` readings; anything older belongs in the
    historical store rather than the live service.
    """
    _require_sensor(sensor_id)
    readings = runtime.simulator.readings(sensor_id, limit=limit, since=since)
    return {
        "sensor_id": sensor_id,
        "count": len(readings),
        "buffer_capacity": SETTINGS.history_readings,
        "readings": readings,
    }


@app.get("/api/v1/sensors/{sensor_id}/health", tags=["health"])
def get_sensor_health(sensor_id: str) -> dict:
    """Health record for one sensor: composite score, sub-scores and notes."""
    _require_sensor(sensor_id)
    record = runtime.health_monitor.sensor_health(sensor_id)
    if record is None:
        raise HTTPException(status_code=503, detail="Health scores are not computed yet")
    return record


@app.get("/api/v1/fleet/health", tags=["health"])
def get_fleet_health(zone_id: Optional[str] = Query(None, description="Filter by zone")) -> dict:
    """Health records for the whole fleet, or for one zone."""
    if zone_id:
        _require_zone(zone_id)
    return {
        "computed_at": runtime.health_monitor.computed_at,
        "summary": runtime.health_monitor.summary(),
        "sensors": runtime.health_monitor.fleet_health(zone_id),
    }


# ---------------------------------------------------------------------------
# Risk and alerts
# ---------------------------------------------------------------------------
@app.get("/api/v1/risk", tags=["risk"])
def get_all_risk() -> dict:
    """Current risk record for every zone."""
    return {
        "simulated_time": runtime.simulator.clock.isoformat(),
        "model": runtime.risk_engine.info()["source"],
        "zones": list(runtime.risk_cache.values()),
    }


@app.get("/api/v1/risk/{zone_id}", tags=["risk"])
def get_zone_risk(zone_id: str) -> dict:
    """Current risk record for one zone."""
    _require_zone(zone_id)
    record = runtime.risk_cache.get(zone_id)
    if record is None:
        raise HTTPException(status_code=503, detail="Risk assessment is not available yet")
    return record


@app.get("/api/v1/alerts", tags=["risk"])
def get_alerts(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Alerts raised since the service started, newest first.

    An alert is raised when a zone's alert level rises, not on every
    assessment, so this is the escalation history rather than a poll log.
    """
    return {"count": len(runtime.alerts), "alerts": list(runtime.alerts)[:limit]}


@app.get("/api/v1/snapshot", tags=["stream"])
def get_snapshot(zone_id: Optional[str] = Query(None, description="Limit to one zone")) -> dict:
    """Complete point-in-time state: zones, conditions, risk, sensors, health
    and recent alerts. Intended as the single call a client makes on page load
    before following the stream."""
    if zone_id:
        _require_zone(zone_id)
    return runtime.snapshot(zone_id)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
@app.get("/api/v1/stream", tags=["stream"])
async def stream_sse(
    request: Request,
    events: Optional[str] = Query(None, description="Comma-separated event types"),
    zones: Optional[str] = Query(None, description="Comma-separated zone ids"),
    sensors: Optional[str] = Query(None, description="Comma-separated sensor ids"),
    sensor_types: Optional[str] = Query(None, description="Comma-separated sensor types"),
    snapshot: bool = Query(False, description="Send a full snapshot before the live events"),
):
    """Server-Sent Events stream of live telemetry.

    Filters are applied at publish time, so a client subscribed to one zone
    never receives the rest of the fleet. A comment line is sent every
    `NER_EWS_HEARTBEAT_S` seconds of silence to keep intermediaries from
    closing an idle connection.
    """
    event_filter = _validate_events(_split(events))
    subscriber_id = f"sse-{uuid4().hex[:12]}"
    try:
        subscription = runtime.bus.subscribe(
            subscriber_id,
            events=event_filter,
            zones=_split(zones),
            sensors=_split(sensors),
            sensor_types=_split(sensor_types),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def generator():
        try:
            yield _sse_inline("stream_open", {
                "subscriber_id": subscriber_id,
                "simulated_time": runtime.simulator.clock.isoformat(),
                "filters": subscription.describe()["filters"],
                "heartbeat_s": SETTINGS.heartbeat_s,
            })
            if snapshot:
                zone_filter = _split(zones)
                only_zone = zone_filter[0] if zone_filter and len(zone_filter) == 1 else None
                yield _sse_inline("snapshot", runtime.snapshot(zone_id=only_zone))

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(subscription.queue.get(),
                                                   timeout=SETTINGS.heartbeat_s)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                subscription.delivered += 1
                yield _sse_packet(event)
        except asyncio.CancelledError:
            raise
        finally:
            runtime.bus.unsubscribe(subscription)
            logger.info("SSE stream %s closed after %d events (%d dropped)",
                        subscriber_id, subscription.delivered, subscription.dropped)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Disables response buffering in nginx, which otherwise holds the
            # stream until its buffer fills and destroys the real-time property.
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/api/v1/ws")
async def stream_websocket(
    websocket: WebSocket,
    events: Optional[str] = Query(None),
    zones: Optional[str] = Query(None),
    sensors: Optional[str] = Query(None),
    sensor_types: Optional[str] = Query(None),
):
    """WebSocket stream carrying the same envelope as the SSE endpoint.

    Initial filters come from the query string. A connected client can change
    them at any time by sending:

        {"action": "subscribe", "zones": ["NER-Z03"], "events": ["sensor_reading"]}

    Other accepted actions are `snapshot`, which returns the current full
    state, and `ping`, which is answered with a `pong` event.
    """
    await websocket.accept()
    subscriber_id = f"ws-{uuid4().hex[:12]}"
    try:
        subscription = runtime.bus.subscribe(
            subscriber_id,
            events=_split(events),
            zones=_split(zones),
            sensors=_split(sensors),
            sensor_types=_split(sensor_types),
        )
    except RuntimeError as exc:
        await websocket.close(code=1013, reason=str(exc))
        return

    await websocket.send_json({
        "event": "stream_open",
        "data": {
            "subscriber_id": subscriber_id,
            "simulated_time": runtime.simulator.clock.isoformat(),
            "filters": subscription.describe()["filters"],
        },
    })

    async def push() -> None:
        while True:
            event = await subscription.queue.get()
            subscription.delivered += 1
            await websocket.send_text(json.dumps(event.envelope(), separators=(",", ":")))

    async def pull() -> None:
        while True:
            message = await websocket.receive_text()
            await _handle_ws_command(websocket, subscription, message)

    push_task = asyncio.create_task(push())
    pull_task = asyncio.create_task(pull())
    try:
        done, pending = await asyncio.wait(
            {push_task, pull_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            # A client that disappears mid-send surfaces either as
            # WebSocketDisconnect on the receive side or as a send-after-close
            # error on the push side. Both are normal disconnections, not
            # service faults, so they are logged rather than raised.
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                logger.exception("WebSocket %s failed", subscriber_id, exc_info=exc)
    except WebSocketDisconnect:
        pass
    finally:
        push_task.cancel()
        pull_task.cancel()
        runtime.bus.unsubscribe(subscription)
        logger.info("WebSocket %s closed after %d events (%d dropped)",
                    subscriber_id, subscription.delivered, subscription.dropped)


async def _handle_ws_command(websocket: WebSocket, subscription: Subscription,
                             message: str) -> None:
    try:
        command = json.loads(message)
    except json.JSONDecodeError:
        await websocket.send_json({"event": "error", "data": {"detail": "Malformed JSON"}})
        return

    action = command.get("action")
    if action == "ping":
        await websocket.send_json({"event": "pong", "data": {
            "simulated_time": runtime.simulator.clock.isoformat()}})
    elif action == "subscribe":
        unknown = [e for e in (command.get("events") or []) if e not in ALL_EVENT_TYPES]
        if unknown:
            await websocket.send_json({"event": "error", "data": {
                "detail": f"Unknown event types {unknown}"}})
            return
        subscription.set_filters(
            events=command.get("events"),
            zones=command.get("zones"),
            sensors=command.get("sensors"),
            sensor_types=command.get("sensor_types"),
        )
        await websocket.send_json({"event": "subscription_updated",
                                   "data": subscription.describe()})
    elif action == "snapshot":
        await websocket.send_json({"event": "snapshot",
                                   "data": runtime.snapshot(command.get("zone_id"))})
    else:
        await websocket.send_json({"event": "error", "data": {
            "detail": f"Unknown action '{action}'. "
                      "Valid actions: subscribe, snapshot, ping"}})


@app.get("/api/v1/stream/stats", tags=["stream"])
def stream_stats() -> dict:
    """Publisher and subscriber statistics, including per-connection drop
    counts. A rising drop count identifies a client that cannot keep up."""
    return runtime.bus.stats()


# ---------------------------------------------------------------------------
# Simulation controls
# ---------------------------------------------------------------------------
@app.post("/api/v1/simulation/rainfall-surge", tags=["simulation"])
def inject_rainfall_surge(request: RainfallSurgeRequest) -> dict:
    """Drives a zone into a sustained heavy rainfall regime.

    Available because waiting for the stochastic rainfall process to produce a
    storm makes the alerting path impractical to demonstrate or test. The surge
    feeds the normal accumulation and saturation path, so the resulting alert
    is produced by the same code that would handle real rainfall.
    """
    _require_zone(request.zone_id)
    result = runtime.simulator.inject_rainfall_surge(
        request.zone_id, request.rate_mm_hr, request.duration_minutes)
    return {"accepted": True, "surge": result}


@app.post("/api/v1/simulation/sensor-fault", tags=["simulation"])
def inject_sensor_fault(request: SensorFaultRequest) -> dict:
    """Forces a named fault onto one sensor, so the quality-control and health
    scoring path can be exercised without waiting for a random failure."""
    _require_sensor(request.sensor_id)
    if request.fault not in FAULT_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fault '{request.fault}'. Valid faults: {sorted(FAULT_PROFILES)}",
        )
    result = runtime.simulator.inject_sensor_fault(
        request.sensor_id, request.fault, request.duration_ticks)
    return {"accepted": True, "fault": result}


@app.post("/api/v1/simulation/clear", tags=["simulation"])
def clear_simulation_faults() -> dict:
    """Clears every active sensor fault and rainfall surge."""
    cleared = runtime.simulator.clear_faults()
    return {"accepted": True, "faults_cleared": cleared}


# ---------------------------------------------------------------------------
# Built-in stream viewer
# ---------------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse, tags=["service"], include_in_schema=False)
def dashboard() -> str:
    """A minimal browser client for the SSE stream.

    Its purpose is to verify the stream end to end and to serve as a worked
    example of consuming it. The operator dashboard is a separate application.
    """
    return _DASHBOARD_HTML


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NER Landslide EWS Sensor Stream</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
         margin: 0; padding: 1.25rem; background: #10141a; color: #dbe3ec; }
  h1 { font-size: 1.05rem; margin: 0 0 0.25rem; letter-spacing: 0.02em; }
  p.sub { margin: 0 0 1rem; color: #8fa0b4; font-size: 0.8rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 0.75rem; margin-bottom: 1rem; }
  .card { background: #182029; border: 1px solid #26313d; border-radius: 6px; padding: 0.75rem; }
  .card h2 { font-size: 0.85rem; margin: 0 0 0.4rem; }
  .row { display: flex; justify-content: space-between; font-size: 0.75rem;
         padding: 0.1rem 0; color: #a9b8c9; }
  .row b { color: #e6edf5; font-weight: 600; }
  .lvl { padding: 0.05rem 0.4rem; border-radius: 3px; font-size: 0.7rem; }
  .Low { background: #1d4231; color: #7ee2b0; }
  .Moderate { background: #4a4021; color: #f0d488; }
  .High { background: #5a3418; color: #ffb27a; }
  .Critical { background: #5c1f22; color: #ff9aa0; }
  #log { background: #0c1116; border: 1px solid #26313d; border-radius: 6px;
         height: 15rem; overflow-y: auto; padding: 0.5rem; font-size: 0.72rem; }
  #log div { padding: 0.05rem 0; color: #8fa0b4; white-space: pre; }
  #status { font-size: 0.75rem; color: #8fa0b4; margin-bottom: 0.6rem; }
</style>
</head>
<body>
<h1>NER Landslide EWS Sensor Stream</h1>
<p class="sub">Live feed over Server-Sent Events from /api/v1/stream</p>
<div id="status">Connecting</div>
<div class="grid" id="zones"></div>
<div id="log"></div>
<script>
const zones = {};
const zoneEl = document.getElementById('zones');
const logEl = document.getElementById('log');
const statusEl = document.getElementById('status');
let received = 0;

function render() {
  zoneEl.innerHTML = Object.values(zones).map(z => `
    <div class="card">
      <h2>${z.zone_name} <span class="lvl ${z.alert_level}">${z.alert_level}</span></h2>
      <div class="row"><span>zone</span><b>${z.zone_id}</b></div>
      <div class="row"><span>risk score</span><b>${z.risk_score}</b></div>
      <div class="row"><span>factor of safety</span><b>${z.physics.factor_of_safety}</b></div>
      <div class="row"><span>saturation</span><b>${z.physics.saturation_ratio}</b></div>
      <div class="row"><span>rain 24h (mm)</span><b>${z.observations.rainfall_24h_mm}</b></div>
      <div class="row"><span>rain now (mm/hr)</span><b>${z.observations.rain_rate_mm_hr}</b></div>
      <div class="row"><span>sensor confidence</span><b>${z.sensor_confidence.confidence}</b></div>
    </div>`).join('');
}

function log(line) {
  const div = document.createElement('div');
  div.textContent = line;
  logEl.prepend(div);
  while (logEl.childElementCount > 300) logEl.removeChild(logEl.lastChild);
}

const source = new EventSource('/api/v1/stream?snapshot=true');
source.addEventListener('stream_open', e => {
  statusEl.textContent = 'Connected as ' + JSON.parse(e.data).subscriber_id;
});
source.addEventListener('snapshot', e => {
  JSON.parse(e.data).zones.forEach(z => { if (z.risk) zones[z.zone_id] = z.risk; });
  render();
});
source.addEventListener('zone_risk', e => {
  zones[JSON.parse(e.data).data.zone_id] = JSON.parse(e.data).data;
  render();
});
source.addEventListener('zone_alert', e => {
  const a = JSON.parse(e.data).data;
  log(`ALERT  ${a.raised_at}  ${a.zone_id}  ${a.previous_level} -> ${a.alert_level}`);
});
source.addEventListener('sensor_fault', e => {
  const f = JSON.parse(e.data).data;
  log(`FAULT  ${f.detected_at}  ${f.sensor_id}  ${f.fault}`);
});
source.addEventListener('sensor_reading', e => {
  const r = JSON.parse(e.data).data;
  received += 1;
  statusEl.textContent = `Connected, ${received} readings received, clock ${r.timestamp}`;
  log(`${r.timestamp}  ${r.sensor_id.padEnd(16)} ${r.sensor_type.padEnd(14)} `
      + `${String(r.value).padStart(9)} ${r.unit}`);
});
source.onerror = () => { statusEl.textContent = 'Disconnected, retrying'; };
</script>
</body>
</html>
"""
