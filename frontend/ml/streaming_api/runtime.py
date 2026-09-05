"""
Streaming Runtime
=================

Purpose
-------
Owns the single background task that drives the whole service. On each tick it
advances the sensor fleet simulator, publishes every reading to the stream bus,
reassesses zone risk, and periodically rescores sensor health. HTTP and
WebSocket handlers never advance the simulation themselves; they read the
state this task maintains, which keeps one authoritative timeline regardless of
how many clients are connected.

Concurrency
-----------
Simulation state is mutated only by the tick task, and only while it holds the
event loop without awaiting. Request handlers are coroutines, so they cannot
interleave with a non-awaiting section, and therefore never observe a
half-updated zone or a reading buffer mid-append. The one heavy step, the
fleet-wide health rescore, is split into a fast collection phase on the loop
and a scoring phase in a worker thread that operates only on copies.

Published events
----------------
    sensor_reading  one per sensor per tick, exactly SENSOR_READING_SCHEMA
    zone_risk       zone risk record, on the risk refresh cadence
    zone_alert      published only when a zone's alert level rises
    sensor_health   fleet health summary, on the health refresh cadence
    sensor_fault    published when a simulated instrument fault begins
    tick            per-tick heartbeat with the simulated clock and counts
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from .config import SETTINGS, Settings
from .health_monitor import FleetHealthMonitor
from .risk_engine import ZoneRiskEngine
from .simulator import SensorFleetSimulator
from .stream_bus import (
    EVENT_SENSOR_FAULT,
    EVENT_SENSOR_HEALTH,
    EVENT_SENSOR_READING,
    EVENT_TICK,
    EVENT_ZONE_ALERT,
    EVENT_ZONE_RISK,
    StreamBus,
)

logger = logging.getLogger("ner_ews.runtime")

ALERT_HISTORY_SIZE = 200


class StreamingRuntime:
    """Simulator, stream bus, risk engine and health monitor as one unit."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or SETTINGS
        self.simulator = SensorFleetSimulator(
            sim_step_s=self.settings.sim_step_s,
            seed=self.settings.seed,
            history_readings=self.settings.history_readings,
            fault_injection=self.settings.fault_injection,
        )
        self.bus = StreamBus(
            queue_size=self.settings.subscriber_queue_size,
            max_subscribers=self.settings.max_subscribers,
        )
        self.risk_engine = ZoneRiskEngine(model_dir=self.settings.model_dir or None)
        self.health_monitor = FleetHealthMonitor(self.simulator)

        self.risk_cache: dict = {}
        self.alerts: deque = deque(maxlen=ALERT_HISTORY_SIZE)
        self.started_at: Optional[str] = None
        self.readings_published = 0
        self.warmup_steps = 0
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return

        # Warm-up runs before the service accepts traffic, so the first request
        # already sees populated rainfall accumulations, saturation state and
        # reading buffers rather than a fleet reporting from zero.
        self.warmup_steps = await asyncio.to_thread(
            self.simulator.warm_up, self.settings.warmup_days, self.settings.max_warmup_steps
        )
        self.health_monitor.refresh()
        self._assess_all_zones()

        self.started_at = datetime.now(timezone.utc).isoformat()
        self._running = True
        self._task = asyncio.create_task(self._run(), name="ner-ews-tick-loop")
        logger.info(
            "Runtime started: %d zones, %d sensors, warm-up %d steps, acceleration %sx",
            len(self.simulator.zones), len(self.simulator.sensors),
            self.warmup_steps, self.settings.time_acceleration,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Runtime stopped after %d readings", self.readings_published)

    @property
    def running(self) -> bool:
        return self._running

    # -----------------------------------------------------------------
    # Tick loop
    # -----------------------------------------------------------------
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        interval = max(self.settings.tick_interval_s, 0.05)
        next_due = loop.time()
        while self._running:
            try:
                await self._tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:                                    # noqa: BLE001
                # A failure in one tick must not take the stream down. The
                # exception is logged and the loop continues on the next tick.
                logger.exception("Tick failed; continuing")

            next_due += interval
            delay = next_due - loop.time()
            if delay < 0:
                # The loop is running behind. Resynchronise rather than
                # accumulating a backlog of immediate ticks.
                next_due = loop.time()
                delay = 0
            await asyncio.sleep(delay)

    async def _tick_once(self) -> None:
        result = self.simulator.tick()
        simulated_time = result["simulated_time"]

        for reading in result["readings"]:
            self.bus.publish(
                EVENT_SENSOR_READING, reading,
                zone_id=reading["zone_id"],
                sensor_id=reading["sensor_id"],
                sensor_type=reading["sensor_type"],
                emitted_at=simulated_time,
            )
        self.readings_published += len(result["readings"])

        for fault in result["faults"]:
            self.bus.publish(
                EVENT_SENSOR_FAULT, fault,
                zone_id=fault["zone_id"],
                sensor_id=fault["sensor_id"],
                sensor_type=fault["sensor_type"],
                emitted_at=simulated_time,
            )

        tick = self.simulator.tick_count

        if tick % max(self.settings.risk_refresh_ticks, 1) == 0:
            for record in self._assess_all_zones():
                self.bus.publish(
                    EVENT_ZONE_RISK, record,
                    zone_id=record["zone_id"],
                    emitted_at=simulated_time,
                )
                self._maybe_alert(record, simulated_time)

        if tick % max(self.settings.health_refresh_ticks, 1) == 0:
            payloads = self.health_monitor.collect()
            cache = await asyncio.to_thread(self.health_monitor.score, payloads)
            self.health_monitor.install(cache, computed_at=simulated_time)
            self.bus.publish(
                EVENT_SENSOR_HEALTH, self.health_monitor.summary(),
                emitted_at=simulated_time,
            )

        self.bus.publish(
            EVENT_TICK,
            {
                "tick": tick,
                "simulated_time": simulated_time,
                "readings": len(result["readings"]),
                "faults": len(result["faults"]),
                "subscribers": self.bus.subscriber_count,
            },
            emitted_at=simulated_time,
        )

    # -----------------------------------------------------------------
    # Derived state
    # -----------------------------------------------------------------
    def _assess_all_zones(self) -> list:
        simulated_time = self.simulator.clock.isoformat()
        records = []
        for zone in self.simulator.zones.values():
            record = self.risk_engine.assess(
                zone,
                sensor_confidence=self.health_monitor.zone_summary(zone.zone_id),
                assessed_at=simulated_time,
            )
            self.risk_cache[zone.zone_id] = record
            records.append(record)
        return records

    def _maybe_alert(self, record: dict, simulated_time: str) -> None:
        zone = self.simulator.zones[record["zone_id"]]
        current = record["alert_level"]
        if not ZoneRiskEngine.is_escalation(zone.last_risk_level, current):
            zone.last_risk_level = current
            return

        alert = {
            "alert_id": f"ALERT-{len(self.alerts) + 1:05d}",
            "zone_id": record["zone_id"],
            "zone_name": record["zone_name"],
            "state": record["state"],
            "district": record["district"],
            "raised_at": simulated_time,
            "previous_level": zone.last_risk_level,
            "alert_level": current,
            "risk_score": record["risk_score"],
            "factor_of_safety": record["physics"]["factor_of_safety"],
            "rainfall_24h_mm": record["observations"]["rainfall_24h_mm"],
            "antecedent_precip_index": record["observations"]["antecedent_precip_index"],
            "sensor_confidence": record["sensor_confidence"].get("confidence"),
            "contributing_factors": record["contributing_factors"],
        }
        zone.last_risk_level = current
        self.alerts.appendleft(alert)
        self.bus.publish(EVENT_ZONE_ALERT, alert, zone_id=record["zone_id"],
                         emitted_at=simulated_time)
        logger.info("Alert %s raised for %s at level %s",
                    alert["alert_id"], alert["zone_id"], current)

    # -----------------------------------------------------------------
    # Read accessors used by the HTTP layer
    # -----------------------------------------------------------------
    def status(self) -> dict:
        return {
            "status": "running" if self._running else "stopped",
            "started_at": self.started_at,
            "simulated_time": self.simulator.clock.isoformat(),
            "tick": self.simulator.tick_count,
            "warmup_steps": self.warmup_steps,
            "zones": len(self.simulator.zones),
            "sensors": len(self.simulator.sensors),
            "readings_published": self.readings_published,
            "alerts_raised": len(self.alerts),
            "clock": {
                "sim_step_s": self.settings.sim_step_s,
                "tick_interval_s": self.settings.tick_interval_s,
                "time_acceleration": self.settings.time_acceleration,
            },
            "stream": {
                "published": self.bus.published,
                "subscribers": self.bus.subscriber_count,
            },
            "model": self.risk_engine.info(),
            "health": self.health_monitor.summary(),
        }

    def snapshot(self, zone_id: Optional[str] = None) -> dict:
        """A complete point-in-time picture. Clients call this once on connect
        and then follow the stream, rather than waiting a full tick to render."""
        zones = [z for z in self.simulator.zones.values()
                 if zone_id is None or z.zone_id == zone_id]
        return {
            "simulated_time": self.simulator.clock.isoformat(),
            "tick": self.simulator.tick_count,
            "zones": [
                {
                    **zone.descriptor(),
                    "conditions": zone.conditions(),
                    "risk": self.risk_cache.get(zone.zone_id),
                }
                for zone in zones
            ],
            "sensors": [
                {
                    **sensor.descriptor(),
                    "latest_reading": self.simulator.latest_reading(sensor.sensor_id),
                    "health": self.health_monitor.sensor_health(sensor.sensor_id),
                }
                for sensor in self.simulator.sensors.values()
                if zone_id is None or sensor.zone_id == zone_id
            ],
            "alerts": list(self.alerts)[:20],
        }
