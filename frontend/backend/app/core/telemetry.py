"""Telemetry driver — the simulated sensor fleet.

Until field hardware exists, this module stands in for the LoRa/GSM gateway. It
writes `SensorReading` rows through exactly the path a real gateway would use, so
replacing it later is a deployment change and not a rewrite.

**The readings are not random numbers.** Each zone carries a physical state that is
advanced every tick, and each sensor reports a projection of that state:

    rainfall  ->  rolling 24h / 72h / 7d accumulation and API
              ->  soil moisture (wetting front, with lag)
              ->  pore pressure (piezometer)
              ->  factor of safety (infinite-slope, after physics_slope_model.py)
              ->  creep rate  ->  tilt and extension
              ->  risk score  ->  alert engine

That ordering is the point. A rainfall burst shows up in the rain gauge first, in
soil moisture an hour later, in pore pressure after that, and in deformation last —
which is what makes the stream useful for testing the alerting and dashboard
layers. Random per-sensor noise would produce numbers that move without meaning
anything, and an operator watching a console that moves for no reason learns to
stop watching it.

The infinite-slope formulation and the saturation/storage treatment follow
`ml/simulation/physics_slope_model.py`; this is the scalar, per-tick form of the
same equations, so the live path and the offline training path cannot drift.

Scenarios are the operator-facing handle. Each one perturbs the *inputs* and lets
the consequences propagate through the real engines rather than writing an outcome
directly — "heavy rainfall" raises rainfall, and the alert that follows is one the
alert engine genuinely decided to raise.
"""
from __future__ import annotations

import logging
import math
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import District, RiskZone, Sensor, SensorReading, WeatherObservation, utcnow
from .stream_bus import (
    EVENT_SENSOR_READING,
    EVENT_TICK,
    EVENT_ZONE_ALERT,
    EVENT_ZONE_RISK,
    bus,
)

log = logging.getLogger("ner.telemetry")

GAMMA_WATER = 9.81           # kN/m3
WETTING_FRONT_FRACTION = 0.35  # a multi-day event wets the upper profile, not all of it


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    summary: str
    chain: tuple[str, ...]
    rain_mm_per_hour: tuple[float, float]     # (min, max) intensity band
    moisture_target: float | None             # % VWC the ground is driven toward
    creep_multiplier: float                   # deformation rate scaling
    fault_fraction: float                     # share of the fleet taken offline
    expected: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="NORMAL",
        label="Normal",
        summary="Baseline monsoon-season conditions with intermittent light rain.",
        chain=("Light rainfall", "Moisture drains", "Risk stable", "No new alerts"),
        rain_mm_per_hour=(0.0, 1.6),
        moisture_target=None,
        creep_multiplier=1.0,
        fault_fraction=0.0,
        expected="Risk drifts down toward the zone's static susceptibility floor.",
    ),
    Scenario(
        key="HEAVY_RAINFALL",
        label="Heavy rainfall",
        summary="A monsoon depression parks over the corridor. Rain gauges climb first.",
        chain=("Rainfall rises", "Soil moisture rises", "Triggering index rises",
               "Risk rises", "Alert engine evaluates", "Rainfall / combined alert"),
        rain_mm_per_hour=(9.0, 22.0),
        moisture_target=None,
        creep_multiplier=1.3,
        fault_fraction=0.0,
        expected="R3 (rainfall threshold) and then R2 (combined) fire as the ground wets up.",
    ),
    Scenario(
        key="SATURATED_SLOPE",
        label="Saturated slope",
        summary="Ground already at field capacity from a previous spell; moderate rain continues.",
        chain=("Soil at saturation", "Pore pressure rises", "Factor of safety falls",
               "Risk rises", "Soil-saturation alert"),
        rain_mm_per_hour=(3.0, 8.0),
        moisture_target=88.0,
        creep_multiplier=2.0,
        fault_fraction=0.0,
        expected="R4 (soil saturation) fires; R2 follows if rainfall keeps up.",
    ),
    Scenario(
        key="SLOPE_MOVEMENT",
        label="Slope movement",
        summary="Measured ground movement — the failure itself, not a proxy for it.",
        chain=("Tilt / extension accumulates", "Movement exceeds limit",
               "Risk floored at critical", "Hazard alert"),
        rain_mm_per_hour=(2.0, 6.0),
        moisture_target=78.0,
        creep_multiplier=14.0,
        fault_fraction=0.0,
        expected="R5 (slope movement) fires at CRITICAL and outranks the other rules.",
    ),
    Scenario(
        key="SENSOR_FAILURE",
        label="Sensor failure",
        summary="Part of the fleet stops reporting. The slope has not changed; our ability to see it has.",
        chain=("Uplinks stop", "Health score falls", "Zone confidence falls",
               "Operational alert", "Hazard alerts flagged low-confidence"),
        rain_mm_per_hour=(0.5, 4.0),
        moisture_target=None,
        creep_multiplier=1.0,
        fault_fraction=0.6,
        expected="R7 (sensor anomaly) raises an OPERATIONAL alert; hazard alerts are not suppressed.",
    ),
)

SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}


# --------------------------------------------------------------------------- #
# Per-district physical state
# --------------------------------------------------------------------------- #
@dataclass
class DistrictState:
    district_id: str
    rain_history: deque = field(default_factory=lambda: deque(maxlen=7 * 24 * 4))
    soil_moisture: float = 45.0
    pore_pressure: float = 8.0
    creep_mm: float = 0.0
    tilt_deg: float = 0.0

    def accumulate(self, now: datetime) -> tuple[float, float, float, float]:
        """Rolling 24h / 72h / 7d totals and the antecedent precipitation index."""
        def total(hours: int) -> float:
            cut = now - timedelta(hours=hours)
            return round(sum(mm for t, mm in self.rain_history if t >= cut), 1)

        r24, r72, r7d = total(24), total(72), total(24 * 7)
        # API_t = P_t + k * API_(t-1), evaluated daily oldest-first (methodology note).
        daily: dict[int, float] = {}
        for t, mm in self.rain_history:
            day = (now - t).days
            daily[day] = daily.get(day, 0.0) + mm
        api = 0.0
        for day in sorted(daily, reverse=True):
            api = daily[day] + settings.api_decay_k * api
        return r24, r72, r7d, round(api, 1)


@dataclass
class SimState:
    scenario: str = "NORMAL"
    scope_id: str = "ALL"
    tick: int = 0
    clock: datetime = field(default_factory=utcnow)
    started_at: datetime = field(default_factory=utcnow)
    districts: dict[str, DistrictState] = field(default_factory=dict)
    offline_sensors: set[str] = field(default_factory=set)
    last_summary: dict = field(default_factory=dict)


_STATE = SimState()
_RNG = random.Random(settings.simulator_seed)


def state() -> SimState:
    return _STATE


# --------------------------------------------------------------------------- #
# Physics
# --------------------------------------------------------------------------- #
def factor_of_safety(slope_deg: float, saturation: float, depth_m: float = 2.0,
                     cohesion_kpa: float = 8.0, friction_deg: float = 30.0,
                     unit_weight: float = 18.0) -> float:
    """Infinite-slope factor of safety. Scalar form of physics_slope_model.py."""
    beta = math.radians(max(1.0, min(80.0, slope_deg)))
    m = max(0.0, min(1.0, saturation))
    u = m * GAMMA_WATER * depth_m * math.cos(beta) ** 2
    numer = cohesion_kpa + (unit_weight * depth_m * math.cos(beta) ** 2 - u) * math.tan(
        math.radians(friction_deg))
    denom = max(1e-6, unit_weight * depth_m * math.sin(beta) * math.cos(beta))
    return max(0.05, min(8.0, numer / denom))


def _moisture_step(current: float, rain_mm: float, hours: float,
                   target: float | None) -> float:
    """Soil moisture responds to rain with lag and drains between spells.

    Saturation is computed against a wetting front rather than the whole soil
    column: full-column storage vastly exceeds any realistic multi-day
    accumulation, which makes moisture insensitive to rainfall and produces a
    flatline nobody believes.
    """
    if target is not None:
        # Scenario pins the ground state; approach it rather than jumping, so the
        # lag between rain and moisture stays visible.
        return round(current + (target - current) * 0.35, 1)
    storage_mm = WETTING_FRONT_FRACTION * 2.0 * 0.42 * 1000.0     # depth x porosity
    gain = (rain_mm / storage_mm) * 100.0 * 3.4
    drain = 0.55 * hours * (1.0 if current > 30 else 0.2)
    return round(max(12.0, min(97.0, current + gain - drain)), 1)


# --------------------------------------------------------------------------- #
# Scenario control
# --------------------------------------------------------------------------- #
def scenarios_payload() -> list[dict]:
    return [
        {
            "key": s.key, "label": s.label, "summary": s.summary,
            "chain": list(s.chain), "expected": s.expected,
            "rainfall_mm_per_hour": list(s.rain_mm_per_hour),
            "active": s.key == _STATE.scenario,
        }
        for s in SCENARIOS
    ]


def state_payload(db: Session | None = None) -> dict:
    s = SCENARIO_BY_KEY.get(_STATE.scenario, SCENARIOS[0])
    return {
        "scenario": _STATE.scenario,
        "scenario_label": s.label,
        "chain": list(s.chain),
        "expected": s.expected,
        "scope_id": _STATE.scope_id,
        "tick": _STATE.tick,
        "simulated_clock": _STATE.clock.isoformat(),
        "started_at": _STATE.started_at.isoformat(),
        "minutes_per_tick": settings.simulator_minutes_per_tick,
        "tick_seconds": settings.simulator_tick_seconds,
        "running": settings.simulator_enabled,
        "offline_sensors": sorted(_STATE.offline_sensors),
        "last_cycle": _STATE.last_summary,
        "provenance": "Simulated telemetry \u00b7 physics-informed",
    }


def apply_scenario(db: Session, scenario: str, scope_id: str = "ALL") -> dict:
    """Switch the fleet onto a scenario and immediately run one tick.

    Immediate rather than waiting for the next scheduled tick: an operator who
    presses a button and sees nothing for twenty seconds concludes the button is
    broken.
    """
    key = (scenario or "NORMAL").upper()
    if key not in SCENARIO_BY_KEY:
        raise ValueError(f"Unknown scenario {scenario}")
    sc = SCENARIO_BY_KEY[key]
    _STATE.scenario = key
    _STATE.scope_id = scope_id or "ALL"

    sensors = _scoped_sensors(db)
    _STATE.offline_sensors.clear()
    if sc.fault_fraction > 0 and sensors:
        # Pick the failures deterministically so a walkthrough is reproducible.
        ordered = sorted(sensors, key=lambda s: s.id)
        count = max(1, int(len(ordered) * sc.fault_fraction))
        # Bias toward sensors that already look weak — that is how fleets actually fail.
        ordered.sort(key=lambda s: (s.battery_pct, s.rssi_dbm))
        for s in ordered[:count]:
            _STATE.offline_sensors.add(s.id)
            # Backdate the last uplink past the health scorer's silence limit, so the
            # operational alert lands on this cycle rather than eight cycles later.
            s.last_seen = utcnow() - timedelta(seconds=s.expected_interval_s * 9)
            s.battery_pct = max(0.0, s.battery_pct - 22)
            s.rssi_dbm = min(-60.0, s.rssi_dbm - 18)

    if sc.moisture_target is not None:
        for st in _states_in_scope(db).values():
            st.soil_moisture = sc.moisture_target

    db.flush()
    return tick(db)


def reset(db: Session) -> dict:
    """Back to NORMAL with a clean fleet."""
    global _STATE, _RNG
    for s in db.scalars(select(Sensor)).all():
        if s.id in _STATE.offline_sensors:
            s.last_seen = utcnow()
            s.battery_pct = min(100.0, s.battery_pct + 22)
            s.rssi_dbm = max(-110.0, s.rssi_dbm + 18)
    db.flush()
    _STATE = SimState()
    _RNG = random.Random(settings.simulator_seed)
    return tick(db)


# --------------------------------------------------------------------------- #
# The tick
# --------------------------------------------------------------------------- #
def _scoped_district_ids(db: Session) -> list[str]:
    ids = [d.id for d in db.scalars(select(District)).all()]
    scope = _STATE.scope_id
    if scope and scope != "ALL":
        return [i for i in ids if i == scope] or ids
    return ids


def _states_in_scope(db: Session) -> dict[str, DistrictState]:
    out = {}
    for did in _scoped_district_ids(db):
        st = _STATE.districts.get(did)
        if st is None:
            st = DistrictState(district_id=did)
            _seed_history(db, st)
            _STATE.districts[did] = st
        out[did] = st
    return out


def _seed_history(db: Session, st: DistrictState) -> None:
    """Warm the rain history from the seeded weather row, so the first tick starts
    from the district's actual antecedent state and not from a dry slate."""
    wx = db.scalars(
        select(WeatherObservation)
        .where(WeatherObservation.district_id == st.district_id)
        .order_by(WeatherObservation.observed_at.desc())
    ).first()
    if not wx:
        return
    now = _STATE.clock
    # Distribute the known totals across the window they describe: last 24h gets
    # r24, the 24-72h band gets (r72 - r24), and so on.
    bands = ((0, 24, wx.rainfall_24h_mm),
             (24, 72, max(0.0, wx.rainfall_72h_mm - wx.rainfall_24h_mm)),
             (72, 168, max(0.0, wx.rainfall_7d_mm - wx.rainfall_72h_mm)))
    for start_h, end_h, total in bands:
        steps = max(1, (end_h - start_h))
        per = total / steps
        for h in range(start_h, end_h):
            st.rain_history.appendleft((now - timedelta(hours=h + 1), per))
    st.soil_moisture = 45.0


def _scoped_sensors(db: Session) -> list[Sensor]:
    ids = set(_scoped_district_ids(db))
    return [s for s in db.scalars(select(Sensor)).all() if s.district_id in ids]


def _sensor_value(sensor: Sensor, st: DistrictState, zone: RiskZone | None,
                  rain_mm_h: float, fos: float) -> float:
    """Each sensor reports a projection of the zone's physical state."""
    t = sensor.sensor_type
    jitter = _RNG.gauss(0, 1)
    if t == "RAIN_GAUGE":
        return round(max(0.0, rain_mm_h + jitter * 0.3), 2)
    if t == "SOIL_MOISTURE":
        return round(max(0.0, min(100.0, st.soil_moisture + jitter * 0.6)), 1)
    if t == "PIEZOMETER":
        return round(max(0.0, st.pore_pressure + jitter * 1.2), 2)
    if t == "TILTMETER":
        return round(st.tilt_deg + jitter * 0.03, 3)
    if t == "EXTENSOMETER":
        return round(st.creep_mm + jitter * 0.18, 2)
    if t == "GEOPHONE":
        # Micro-seismic activity rises as the slope approaches limit equilibrium.
        base = 28.0 + max(0.0, (1.6 - fos)) * 34.0
        return round(max(0.0, base + jitter * 1.5), 1)
    if t == "WEATHER_STATION":
        return round(21.0 - rain_mm_h * 0.12 + jitter * 0.4, 1)
    return round(max(0.0, jitter), 2)


def tick(db: Session) -> dict:
    """Advance the simulation one step and run a full risk cycle.

    Deliberately calls `run_risk_cycle` rather than touching risk or alerts here:
    the simulator's job ends at producing telemetry. Everything downstream is the
    same code that would run against a real gateway.
    """
    from ..services import run_risk_cycle       # local import: avoids a cycle

    sc = SCENARIO_BY_KEY.get(_STATE.scenario, SCENARIOS[0])
    minutes = settings.simulator_minutes_per_tick
    hours = minutes / 60.0
    _STATE.clock = _STATE.clock + timedelta(minutes=minutes)
    _STATE.tick += 1
    now = utcnow()

    states = _states_in_scope(db)
    zones = {z.id: z for z in db.scalars(select(RiskZone)).all()}
    district_zone = {}
    for z in zones.values():
        district_zone.setdefault(z.district_id, z)

    readings = 0
    for did, st in states.items():
        lo, hi = sc.rain_mm_per_hour
        rain_mm_h = max(0.0, _RNG.uniform(lo, hi))
        st.rain_history.append((_STATE.clock, rain_mm_h * hours))
        r24, r72, r7d, api = st.accumulate(_STATE.clock)

        st.soil_moisture = _moisture_step(st.soil_moisture, rain_mm_h * hours,
                                          hours, sc.moisture_target)

        zone = district_zone.get(did)
        slope = zone.slope_deg if zone else 34.0
        saturation = st.soil_moisture / 100.0
        fos = factor_of_safety(slope, saturation)
        st.pore_pressure = round(saturation * GAMMA_WATER * 2.0
                                 * math.cos(math.radians(slope)) ** 2, 2)

        # Creep accelerates as the factor of safety approaches unity. Below FS 1.0
        # the slope is failing, not creeping, and the rate should say so.
        proximity = max(0.0, min(1.0, (1.8 - fos) / 0.8))
        rate = 0.012 * sc.creep_multiplier * (proximity ** 2)
        st.creep_mm = round(st.creep_mm + rate * minutes, 3)
        st.tilt_deg = round(st.tilt_deg + rate * minutes * 0.055, 4)

        db.add(WeatherObservation(
            district_id=did,
            district=zone.district if zone else did,
            observed_at=now,
            rainfall_now_mm=round(rain_mm_h, 2),
            rainfall_24h_mm=r24, rainfall_72h_mm=r72, rainfall_7d_mm=r7d,
            humidity_pct=round(min(99.0, 62 + rain_mm_h * 2.6), 1),
            temperature_c=round(21.5 - rain_mm_h * 0.12, 1),
            wind_kph=round(6 + rain_mm_h * 0.9, 1),
            condition=("HEAVY_RAIN" if rain_mm_h >= 8 else
                       "LIGHT_RAIN" if rain_mm_h >= 0.5 else "CLOUDY"),
            alert_threshold_24h=next(
                (d.alert_threshold_24h for d in db.scalars(select(District)).all()
                 if d.id == did), 95.0),
            forecast=[],
            source="SIMULATED_TELEMETRY",
        ))

        for zone_row in (z for z in zones.values() if z.district_id == did):
            zone_row.antecedent_precip_index = api

        for sensor in db.scalars(select(Sensor).where(Sensor.district_id == did)).all():
            if sensor.id in _STATE.offline_sensors:
                continue                      # a silent sensor writes nothing. That is the point.
            value = _sensor_value(sensor, st, zones.get(sensor.zone_id), rain_mm_h, fos)
            db.add(SensorReading(
                sensor_id=sensor.id, timestamp=now, value=value,
                unit=sensor.unit, quality_flag="OK", received_at=now,
            ))
            sensor.reading = value
            sensor.last_seen = now
            sensor.battery_pct = round(max(3.0, sensor.battery_pct - 0.02), 1)
            sensor.rssi_dbm = round(
                max(-118.0, min(-58.0, sensor.rssi_dbm + _RNG.gauss(0, 1.2))), 1)
            readings += 1

    db.commit()

    # Publish the readings before the risk cycle runs, so a subscribed dashboard
    # shows the telemetry that caused an alert arriving ahead of the alert itself.
    # The other order makes the console look like it is warning about nothing.
    for sensor in db.scalars(select(Sensor)).all():
        if sensor.id in _STATE.offline_sensors or sensor.district_id not in states:
            continue
        bus.publish(
            EVENT_SENSOR_READING,
            {
                "sensor_id": sensor.id, "zone_id": sensor.zone_id,
                "sensor_type": sensor.sensor_type, "value": sensor.reading,
                "unit": sensor.unit, "battery_pct": sensor.battery_pct,
                "rssi_dbm": sensor.rssi_dbm, "timestamp": now.isoformat(),
                "expected_interval_s": sensor.expected_interval_s,
            },
            zone_id=sensor.zone_id, sensor_id=sensor.id,
            sensor_type=sensor.sensor_type,
        )

    cycle = run_risk_cycle(db, send=True)

    for zone in db.scalars(select(RiskZone)).all():
        if zone.district_id not in states:
            continue
        bus.publish(
            EVENT_ZONE_RISK,
            {
                "zone_id": zone.id, "name": zone.name, "district": zone.district,
                "risk_score": zone.risk_score, "risk_level": zone.risk_level,
                "probability": zone.probability, "alert_tier": zone.alert_tier,
                "sensor_confidence": zone.sensor_confidence, "source": zone.source,
            },
            zone_id=zone.id,
        )

    bus.publish(EVENT_TICK, {
        "tick": _STATE.tick, "scenario": _STATE.scenario,
        "readings_written": readings, **{k: cycle.get(k) for k in
                                          ("alerts_created", "alerts_escalated", "zones_scored")},
    })
    _STATE.last_summary = {
        "tick": _STATE.tick,
        "scenario": _STATE.scenario,
        "readings_written": readings,
        "alerts_created": cycle.get("alerts_created", 0),
        "alerts_escalated": cycle.get("alerts_escalated", 0),
        "zones_scored": cycle.get("zones_scored", 0),
        "ran_at": cycle.get("ran_at"),
    }
    return {**state_payload(db), "cycle": cycle, "readings_written": readings}
