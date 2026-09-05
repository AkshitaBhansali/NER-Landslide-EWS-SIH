"""Application entrypoint.

    uvicorn app.main:app --reload --port 8000

Docs at /docs. Health at /api/health.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .config import settings
from .db import Base, engine, get_db, session
from .deps import Session, make_token
from .models import User
from .core import stream_bus, telemetry
from .routers import (
    alerts,
    custom_alerts,
    gis,
    incidents,
    ingest,
    platform,
    reports,
    risk,
    sensors,
    simulation,
    sync,
)
from .services import run_risk_cycle, system_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ner.main")


class Hub:
    """Websocket fan-out, backed by the filtered stream bus.

    Deliberately not a message broker. At district scale the connection count is in
    the tens, and adding Redis here would be infrastructure the deployment target
    cannot maintain. If this ever needs to scale past one process, the swap point is
    `broadcast`, and nothing else changes.

    Every message is also published on `bus`, which applies per-subscriber filters at
    publish time and a bounded-queue backpressure policy. That is what lets the SSE
    endpoint serve a client watching one district without shipping it the whole
    region, and stops one slow reader from stalling the others.
    """

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        # Mirror onto the filtered bus first: SSE subscribers and websocket clients
        # must see the same timeline, or a dashboard using one transport disagrees
        # with a dashboard using the other.
        payload = message.get("payload") or {}
        bus.publish(
            _BUS_EVENTS.get(message.get("type", ""), stream_bus.EVENT_TICK),
            payload if isinstance(payload, dict) else {"value": payload},
            zone_id=payload.get("zone_id") if isinstance(payload, dict) else None,
            sensor_id=payload.get("sensor_id") if isinstance(payload, dict) else None,
        )
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


bus = stream_bus.bus
_BUS_EVENTS = stream_bus.PLATFORM_EVENTS

hub = Hub()


async def _scheduler() -> None:
    """Periodic risk cycle. The platform's heartbeat."""
    while True:
        await asyncio.sleep(settings.risk_recompute_seconds)
        try:
            db = session()
            try:
                result = await asyncio.to_thread(run_risk_cycle, db, True)
                log.info("risk cycle: %s", result)
                if result.get("alerts_created") or result.get("alerts_escalated"):
                    await hub.broadcast({"type": "RISK_CYCLE", "payload": result})
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            log.exception("risk cycle failed")   # never let one bad tick kill the loop


async def _telemetry_loop() -> None:
    """Advance the simulated fleet on a fixed cadence.

    Separate from the risk scheduler because the two answer different questions:
    the scheduler guarantees a recompute even when nothing arrives, while this loop
    is what makes readings arrive at all. In a deployment with real gateways this
    task is switched off (SIMULATOR_ENABLED=false) and nothing else changes.
    """
    while True:
        await asyncio.sleep(settings.simulator_tick_seconds)
        try:
            db = session()
            try:
                result = await asyncio.to_thread(telemetry.tick, db)
                cycle = result.get("cycle", {})
                if cycle.get("alerts_created") or cycle.get("alerts_escalated"):
                    await hub.broadcast({"type": "RISK_CYCLE", "payload": cycle})
                await hub.broadcast({"type": "TELEMETRY", "payload": {
                    "tick": result.get("tick"),
                    "scenario": result.get("scenario"),
                    "readings_written": result.get("readings_written"),
                }})
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            log.exception("telemetry tick failed")   # one bad tick must not stop the fleet


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    tasks = []
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(_scheduler()))
    if settings.simulator_enabled:
        tasks.append(asyncio.create_task(_telemetry_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Backend, risk engine, alert engine and offline sync for the NER Landslide "
        "Early Warning System (SIH PS 26001, MDoNER).\n\n"
        "**All data is synthetic and labelled as such.** This service has no authority "
        "to issue an official warning."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "X-Data-Confidence"],
)

# custom_alerts is registered BEFORE alerts: both live under /api/alerts, and the
# alerts router's /{alert_id} would otherwise swallow /custom as an alert id.
for r in (risk.router, custom_alerts.router, alerts.router, sensors.router, gis.router,
          incidents.router, reports.router, platform.router, sync.router,
          ingest.router, simulation.router):
    app.include_router(r)


@app.get("/api/health", tags=["platform"])
def health(db: Session = Depends(get_db)):
    return system_status(db)


@app.post("/api/auth/login", tags=["platform"])
def login(body: dict, db: Session = Depends(get_db)):
    u = db.scalars(select(User).where(User.username == body.get("username"))).first()
    pw = hashlib.sha256((body.get("password") or "").encode()).hexdigest()
    if not u or u.password_hash != pw or not u.active:
        raise HTTPException(401, "Invalid credentials")
    return {
        "token": make_token(u.username, u.role, u.district_id),
        "user": {"username": u.username, "display_name": u.display_name,
                 "role": u.role, "district_id": u.district_id, "language": u.language},
        "auth_enabled": settings.auth_enabled,
    }


@app.websocket("/api/ws")
async def ws(websocket: WebSocket):
    """Live push. The console can subscribe instead of polling every 30 s — which on
    a district office's metered link is the difference between usable and not."""
    await hub.connect(websocket)
    try:
        await websocket.send_json({"type": "HELLO", "payload": {"version": settings.version}})
        while True:
            await websocket.receive_text()   # keepalive
    except WebSocketDisconnect:
        hub.disconnect(websocket)


@app.get("/api/stream", tags=["platform"])
async def stream(
    request: Request,
    events: str | None = None,
    zones: str | None = None,
    sensors: str | None = None,
    sensor_types: str | None = None,
):
    """Server-Sent Events feed of live platform state.

    SSE alongside the existing websocket because they suit different clients. A
    browser dashboard wants one long-lived connection with automatic reconnection
    and no client library; a map that re-subscribes when the operator selects a
    different district wants a websocket it can talk back on. Both read the same bus,
    so they cannot show different timelines.

    Filters are comma-separated and applied at publish time, so a client watching one
    district never receives the rest of the region:

        /api/stream?events=zone_alert&zones=nl-kohima-z1

    Every event carries a monotonic `seq`. If a client falls behind, the bus drops
    its oldest queued event rather than stalling the producer, and the gap in `seq`
    is how the client knows to refill from the REST history endpoints.
    """
    sub = bus.subscribe(
        subscriber_id=f"sse-{id(request)}",
        events=events.split(",") if events else None,
        zones=zones.split(",") if zones else None,
        sensors=sensors.split(",") if sensors else None,
        sensor_types=sensor_types.split(",") if sensor_types else None,
    )

    async def gen():
        try:
            yield (": connected\n\n")
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # A comment frame keeps proxies from closing an idle connection.
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event.event}\ndata: {json.dumps(event.envelope())}\n\n"
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/stream/status", tags=["platform"])
def stream_status():
    """Subscriber count and drop counters — whether anyone is falling behind."""
    return bus.stats() if hasattr(bus, "stats") else {
        "subscribers": bus.subscriber_count(),
    }


@app.get("/", include_in_schema=False)
def root():
    return JSONResponse({
        "service": settings.app_name,
        "version": settings.version,
        "docs": "/docs",
        "health": "/api/health",
        "data_confidence": settings.data_confidence,
        "note": "Synthetic data. Not an official warning system.",
    })
