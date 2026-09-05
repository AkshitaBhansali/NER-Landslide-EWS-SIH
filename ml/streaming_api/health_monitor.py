"""
Live Sensor Health Monitor
==========================

Purpose
-------
Applies the offline quality-control stack to the live stream. For each sensor
the recent reading buffer is passed through
`data_pipeline.data_quality.SensorStreamCleaner` and then scored by
`data_pipeline.sensor_health.SensorHealthScorer`, producing the same 0-100
health score and status that the offline pipeline produces. The API serves
those scores next to every risk prediction, so an operator can tell a high
risk score backed by healthy instruments apart from one backed by a sensor
that has been drifting for two days.

Scoring cadence
---------------
Cleaning and scoring the whole fleet is pandas work over a rolling buffer,
which is far heavier than a single simulation tick. It therefore runs on its
own cadence (`health_refresh_ticks`) rather than once per reading, and the
service serves the cached result in between. The cache carries the simulated
timestamp it was computed at, so a client can tell how fresh it is.

Known limitation
----------------
`SensorStreamCleaner.detect_drift` compares each rolling window against the
first window of the buffer. That test is valid for a quasi-stationary signal,
but the channels here are rainfall-driven and genuinely non-stationary: soil
moisture really does climb by twenty points during a storm. Run at the default
z-threshold the test would report drift for every sensor in every storm, so
the live monitor raises the threshold and treats stability as a weak signal.
Separating instrument drift from real hydrological trend requires comparing a
sensor against its own modelled expectation, which is future work rather than
something the current cleaner does.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]   # <repo>/ml
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_pipeline.data_quality import SensorStreamCleaner        # noqa: E402
from data_pipeline.sensor_health import SensorHealthScorer        # noqa: E402

# See "Known limitation" above.
LIVE_DRIFT_Z_THRESHOLD = 6.0

# Minimum buffered readings before a score is meaningful. Below this the
# monitor reports a warming-up status instead of a misleadingly low score.
MIN_READINGS_FOR_SCORE = 24


class FleetHealthMonitor:
    """Cleans and scores the reading buffer of every simulated sensor."""

    def __init__(self, simulator, drift_window: int = 24):
        self.simulator = simulator
        self.scorer = SensorHealthScorer()
        self.drift_window = drift_window
        self._cache: dict = {}
        self.computed_at: Optional[str] = None
        self.refresh_count = 0

    # -----------------------------------------------------------------
    # Two-phase scoring.
    #
    # collect() reads the simulator's live buffers and must run on the event
    # loop, where no request handler can interleave with the tick task. score()
    # is pure computation over those copies and is therefore safe to hand to a
    # worker thread, which keeps a fleet-wide rescore from stalling connected
    # streams.
    # -----------------------------------------------------------------
    def collect(self) -> list:
        now_iso = self.simulator.clock.isoformat()
        return [
            {
                "sensor_id": sensor.sensor_id,
                "zone_id": sensor.zone_id,
                "sensor_type": sensor.sensor_type,
                "expected_interval_s": sensor.expected_interval_s,
                "battery_pct": sensor.battery_pct,
                "rssi_dbm": sensor.rssi_dbm,
                "fault_state": sensor.fault or "nominal",
                "history": [(r["timestamp"], r["value"]) for r in sensor.history],
                "now": now_iso,
            }
            for sensor in self.simulator.sensors.values()
        ]

    def _score_payload(self, payload: dict) -> dict:
        history = payload["history"]
        if len(history) < MIN_READINGS_FOR_SCORE:
            return {
                "sensor_id": payload["sensor_id"],
                "zone_id": payload["zone_id"],
                "sensor_type": payload["sensor_type"],
                "status": "Warming up",
                "health_score": None,
                "fault_state": payload["fault_state"],
                "readings_buffered": len(history),
                "notes": [f"Fewer than {MIN_READINGS_FOR_SCORE} readings buffered"],
            }

        frame = pd.DataFrame(history, columns=["timestamp", "value"])
        cleaner = SensorStreamCleaner(
            expected_interval_s=payload["expected_interval_s"],
            drift_window=self.drift_window,
            drift_z_threshold=LIVE_DRIFT_Z_THRESHOLD,
        )
        cleaned = cleaner.clean(frame)

        last_ts = pd.to_datetime(history[-1][0])
        now = pd.to_datetime(payload["now"])
        hours_since_last = max((now - last_ts).total_seconds() / 3600.0, 0.0)

        result = self.scorer.score(
            sensor_id=payload["sensor_id"],
            sensor_type=payload["sensor_type"],
            cleaned_stream=cleaned,
            n_expected=len(cleaned),
            comms_failures=cleaner.report.get("comms_failures_detected", 0),
            battery_pct=payload["battery_pct"],
            hours_since_last=hours_since_last,
        )

        return {
            "sensor_id": result.sensor_id,
            "zone_id": payload["zone_id"],
            "sensor_type": result.sensor_type,
            "health_score": result.health_score,
            "status": result.status,
            "sub_scores": {
                "completeness": result.completeness,
                "validity": result.validity,
                "stability": result.stability,
                "noise": result.noise,
                "comms": result.comms,
            },
            "battery_pct": round(payload["battery_pct"], 1),
            "rssi_dbm": round(payload["rssi_dbm"], 1),
            "fault_state": payload["fault_state"],
            "readings_buffered": len(history),
            "comms_failures_in_window": cleaner.report.get("comms_failures_detected", 0),
            "longest_gap_hours": cleaner.report.get("longest_gap_hours", 0.0),
            "hours_since_last_reading": round(hours_since_last, 3),
            "notes": result.notes,
        }

    def score(self, payloads: list) -> dict:
        """Scores collected payloads. Pure computation, safe off the event loop."""
        return {p["sensor_id"]: self._score_payload(p) for p in payloads}

    def install(self, cache: dict, computed_at: Optional[str] = None) -> dict:
        self._cache = cache
        self.computed_at = computed_at or self.simulator.clock.isoformat()
        self.refresh_count += 1
        return self._cache

    def refresh(self) -> dict:
        """Collects, scores and installs in one call. Used by the synchronous
        entry points; the service splits the phases across a worker thread."""
        return self.install(self.score(self.collect()))

    # --- accessors, all served from cache ---
    def sensor_health(self, sensor_id: str) -> Optional[dict]:
        return self._cache.get(sensor_id)

    def fleet_health(self, zone_id: Optional[str] = None) -> list:
        rows = list(self._cache.values())
        if zone_id:
            rows = [r for r in rows if r["zone_id"] == zone_id]
        return rows

    def zone_summary(self, zone_id: str) -> dict:
        """Aggregate sensor confidence for one zone, attached to its risk record."""
        rows = self.fleet_health(zone_id)
        scored = [r for r in rows if r.get("health_score") is not None]
        reporting = [r for r in rows if r.get("fault_state") != "comms_dropout"]

        if not scored:
            return {
                "mean_health_score": None,
                "sensors_total": len(rows),
                "sensors_reporting": len(reporting),
                "sensors_degraded": 0,
                "confidence": "unknown",
            }

        mean_score = round(sum(r["health_score"] for r in scored) / len(scored), 1)
        degraded = sum(1 for r in scored if r["health_score"] < 60)

        if mean_score >= 80:
            confidence = "high"
        elif mean_score >= 60:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "mean_health_score": mean_score,
            "sensors_total": len(rows),
            "sensors_reporting": len(reporting),
            "sensors_degraded": degraded,
            "confidence": confidence,
        }

    def summary(self) -> dict:
        rows = [r for r in self._cache.values() if r.get("health_score") is not None]
        by_status: dict = {}
        for row in self._cache.values():
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        return {
            "computed_at": self.computed_at,
            "refresh_count": self.refresh_count,
            "sensors_scored": len(rows),
            "mean_health_score": round(sum(r["health_score"] for r in rows) / len(rows), 1) if rows else None,
            "by_status": by_status,
        }
