"""
Streaming API Configuration
===========================

Purpose
-------
Central configuration for the real-time sensor streaming service. Every value
is overridable through an environment variable prefixed with `NER_EWS_`, so
the same code runs as a fast demo (accelerated simulated clock) or as a
production-cadence service (one emission per real reporting interval) without
a code change.

Clock model
-----------
The service maintains a simulated clock separate from wall-clock time. Each
tick of the simulator advances the simulated clock by `sim_step_s` and then
sleeps `tick_interval_s` of real time. The ratio of the two is the time
acceleration factor:

    acceleration = sim_step_s / tick_interval_s

With the defaults (300 simulated seconds per 2 real seconds) the service
delivers a 5-minute sensor cadence every 2 seconds, which is 150x real time.
Setting `NER_EWS_TICK_INTERVAL_S=300` returns the service to real time.

Every emitted reading carries `expected_interval_s = sim_step_s`, so the
downstream gap and communication-failure detection in
`data_pipeline.data_quality.SensorStreamCleaner` stays correct at any
acceleration factor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_str(name: str, default: str) -> str:
    return os.environ.get(f"NER_EWS_{name}", default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(f"NER_EWS_{name}", default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(f"NER_EWS_{name}", default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(f"NER_EWS_{name}")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime settings for the streaming service."""

    # --- clock ---
    sim_step_s: int = field(default_factory=lambda: _env_int("SIM_STEP_S", 300))
    tick_interval_s: float = field(default_factory=lambda: _env_float("TICK_INTERVAL_S", 2.0))

    # --- simulator ---
    seed: int = field(default_factory=lambda: _env_int("SEED", 42))
    warmup_days: float = field(default_factory=lambda: _env_float("WARMUP_DAYS", 7.0))
    max_warmup_steps: int = field(default_factory=lambda: _env_int("MAX_WARMUP_STEPS", 20000))
    history_readings: int = field(default_factory=lambda: _env_int("HISTORY_READINGS", 288))
    fault_injection: bool = field(default_factory=lambda: _env_bool("FAULT_INJECTION", True))

    # --- derived analytics cadence, in ticks ---
    risk_refresh_ticks: int = field(default_factory=lambda: _env_int("RISK_REFRESH_TICKS", 1))
    health_refresh_ticks: int = field(default_factory=lambda: _env_int("HEALTH_REFRESH_TICKS", 12))

    # --- transport ---
    subscriber_queue_size: int = field(default_factory=lambda: _env_int("SUBSCRIBER_QUEUE_SIZE", 512))
    heartbeat_s: float = field(default_factory=lambda: _env_float("HEARTBEAT_S", 15.0))
    max_subscribers: int = field(default_factory=lambda: _env_int("MAX_SUBSCRIBERS", 64))
    cors_origins: str = field(default_factory=lambda: _env_str("CORS_ORIGINS", "*"))

    # --- service ---
    host: str = field(default_factory=lambda: _env_str("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    model_dir: str = field(default_factory=lambda: _env_str("MODEL_DIR", ""))

    @property
    def time_acceleration(self) -> float:
        if self.tick_interval_s <= 0:
            return 1.0
        return round(self.sim_step_s / self.tick_interval_s, 2)

    @property
    def cors_origin_list(self) -> list:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def as_dict(self) -> dict:
        return {
            "sim_step_s": self.sim_step_s,
            "tick_interval_s": self.tick_interval_s,
            "time_acceleration": self.time_acceleration,
            "seed": self.seed,
            "warmup_days": self.warmup_days,
            "history_readings": self.history_readings,
            "fault_injection": self.fault_injection,
            "risk_refresh_ticks": self.risk_refresh_ticks,
            "health_refresh_ticks": self.health_refresh_ticks,
            "subscriber_queue_size": self.subscriber_queue_size,
            "heartbeat_s": self.heartbeat_s,
            "max_subscribers": self.max_subscribers,
        }


SETTINGS = Settings()
