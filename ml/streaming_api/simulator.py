"""
Live Sensor Fleet Simulator
===========================

Purpose
-------
Produces the real-time sensor stream that the API serves. Until field hardware
is installed, this module stands in for the LoRa and GSM gateway that will
eventually push readings into the platform. It emits records that conform
exactly to `data_pipeline.schema.SENSOR_READING_SCHEMA`, so replacing the
simulator with a real gateway ingestion path requires no change to the stream
bus, the REST layer, the health scorer or the risk engine.

Design
------
Readings are not random noise. Every zone carries a physical state that is
advanced on each tick, and each sensor reports a projection of that state:

1. A rainfall process drives the zone. Rainfall follows a four-state Markov
   chain (dry, light, moderate, heavy) with monsoon seasonality and a
   per-zone intensity multiplier, which reproduces the burst structure of NER
   rainfall rather than independent draws per reading.
2. Rolling 24-hour, 72-hour and 7-day accumulations and the antecedent
   precipitation index are recomputed from the rainfall history, using the
   same weights as `simulation.physics_slope_model`.
3. The infinite-slope Factor of Safety is recomputed from the current
   saturation ratio, giving each zone a live stability state.
4. Sensors read off that state. A piezometer reports the modelled pore
   pressure, a soil moisture probe reports saturation, and the deformation
   sensors (tiltmeter and extensometer) accumulate creep at a rate that grows
   as the Factor of Safety approaches one.

The result is a stream in which a rainfall burst propagates through soil
moisture, then pore pressure, then deformation, then risk score, in the
correct physical order and with the correct lags. That is what makes the
stream useful for testing the alerting and dashboard layers.

Wetting front
-------------
Saturation is computed against a wetting front rather than the entire soil
column. `research/dataset_construction.md` records that using full-column
storage makes the saturation ratio insensitive to rainfall, because storage
capacity greatly exceeds any realistic multi-day accumulation. A rainfall
event wets only the upper part of the profile within its duration, so the
live model applies `WETTING_FRONT_FRACTION` to the storage term. This affects
the live stream only; the committed physics dataset is unchanged.

Sensor faults
-------------
Field sensors fail, and a stream in which nothing ever fails cannot exercise
the quality-control path. The simulator injects communication dropouts, stuck
readings, calibration drift and noise bursts at low probability, along with
gradual battery discharge and variable signal strength. These are what
`data_pipeline.data_quality.SensorStreamCleaner` and
`data_pipeline.sensor_health.SensorHealthScorer` are built to detect, so the
health scores served by the API move for real reasons.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

GAMMA_WATER = 9.81  # kN/m3, unit weight of water

# Fraction of the soil column a multi-day rainfall event actually wets. See the
# module docstring for the rationale.
WETTING_FRONT_FRACTION = 0.35

# Units per sensor type, matching SENSOR_READING_SCHEMA.
SENSOR_UNITS = {
    "rain_gauge": "mm/hr",
    "soil_moisture": "pct",
    "piezometer": "kPa",
    "tiltmeter": "deg",
    "extensometer": "mm",
    "geophone": "mm/s",
}

# Short codes used to build sensor identifiers.
SENSOR_TYPE_CODES = {
    "rain_gauge": "RG",
    "soil_moisture": "SM",
    "piezometer": "PZ",
    "tiltmeter": "TM",
    "extensometer": "EX",
    "geophone": "GP",
}

# Instrument noise, one standard deviation. Each value is 0.6 times the
# corresponding datasheet reference in
# data_pipeline.sensor_health.EXPECTED_NOISE_STD, so a nominal sensor sits
# comfortably inside its noise specification and scores full marks, while an
# injected noise burst pushes it far enough past the reference to be caught.
SENSOR_NOISE_STD = {
    "rain_gauge": 0.30,
    "soil_moisture": 0.60,
    "piezometer": 1.20,
    "tiltmeter": 0.03,
    "extensometer": 0.18,
    "geophone": 0.18,
}

# Fault catalogue. Each entry gives a relative weight and a duration range in
# ticks, so faults persist long enough for the cleaner to detect them.
FAULT_PROFILES = {
    "comms_dropout": {"weight": 0.40, "min_ticks": 3, "max_ticks": 30},
    "stuck_reading": {"weight": 0.20, "min_ticks": 12, "max_ticks": 60},
    "calibration_drift": {"weight": 0.25, "min_ticks": 40, "max_ticks": 160},
    "noise_burst": {"weight": 0.15, "min_ticks": 6, "max_ticks": 40},
}

# Probability that a nominal sensor enters a fault state on a given tick.
FAULT_ONSET_PROBABILITY = 0.0015

# Rainfall regimes and their per-five-minute transition probabilities. These
# are calibrated so that a zone of intensity 1.0 receives roughly 25 mm per day
# through the monsoon, with a 24-hour 99th percentile near 110 mm and 7-day
# totals in the 150 to 330 mm range, which matches the observed distribution
# for the hill districts of the region.
RAIN_REGIMES = ("dry", "light", "moderate", "heavy")
RAIN_TRANSITIONS = {
    0: {1: 0.0028},
    1: {0: 0.040, 2: 0.018},
    2: {1: 0.055, 3: 0.008},
    3: {2: 0.085},
}
RAIN_RATE_RANGES = {
    0: (0.0, 0.0),
    1: (0.2, 2.0),
    2: (2.0, 8.0),
    3: (8.0, 30.0),
}


def _seasonal_factors(month: int) -> tuple:
    """Returns (wetting_multiplier, drying_multiplier) for the given month.

    The NER monsoon runs June to September and carries the overwhelming
    majority of landslide-triggering rainfall. Pre-monsoon thunderstorm
    activity in April and May is significant but shorter-lived, and the winter
    months are close to dry.

    Seasonality is applied only to transitions into and out of the dry regime,
    which are storm onset and storm termination. Escalation between light,
    moderate and heavy rain within a storm is a property of the storm rather
    than of the season, so those transitions are left unscaled.
    """
    if 6 <= month <= 9:
        return 2.5, 0.6
    if month in (4, 5, 10):
        return 1.4, 0.9
    return 0.3, 1.6


def _scale_probability(p_per_5min: float, step_s: int) -> float:
    """Rescales a per-five-minute probability to the configured step length,
    so regime dwell times stay the same at any simulation cadence."""
    if step_s == 300:
        return p_per_5min
    exponent = step_s / 300.0
    return 1.0 - (1.0 - min(max(p_per_5min, 0.0), 1.0)) ** exponent


# ---------------------------------------------------------------------------
# Monitored zones
# ---------------------------------------------------------------------------
# Six instrumented corridors across the eight NER states, chosen because each
# has a documented history of rainfall-triggered slope failure affecting a
# lifeline road, rail or urban settlement. Geotechnical parameters are
# representative values for the colluvial and residual soils typical of each
# corridor, and are the values a site survey would replace with measured data.
#
# Parameters are set so that each zone is comfortably stable when dry
# (Factor of Safety 1.30 to 1.75) and reaches or approaches failure when the
# slip surface saturates (0.77 to 0.99). A slope that cannot fail under any
# rainfall makes the zone useless for testing the alerting path, and one that
# fails in ordinary rain makes the dashboard permanently red, so the response
# curve matters more than any single parameter value.
ZONE_DEFINITIONS = [
    dict(zone_id="NER-Z01", name="NH-10 Teesta Corridor", state="Sikkim",
         district="Pakyong", latitude=27.1560, longitude=88.4620,
         elevation_m=780.0, slope_deg=34.0, soil_depth_m=2.4, porosity=0.44,
         cohesion_kpa=7.0, friction_angle_deg=36.0, unit_weight_kn_m3=18.5,
         rain_intensity=1.15, terrain_shielding=0.9),
    dict(zone_id="NER-Z02", name="Sohra Plateau Escarpment", state="Meghalaya",
         district="East Khasi Hills", latitude=25.2700, longitude=91.7320,
         elevation_m=1290.0, slope_deg=30.0, soil_depth_m=1.8, porosity=0.47,
         cohesion_kpa=6.5, friction_angle_deg=34.0, unit_weight_kn_m3=17.8,
         rain_intensity=1.85, terrain_shielding=0.75),
    dict(zone_id="NER-Z03", name="Aizawl Urban Slopes", state="Mizoram",
         district="Aizawl", latitude=23.7270, longitude=92.7170,
         elevation_m=1130.0, slope_deg=33.0, soil_depth_m=2.0, porosity=0.42,
         cohesion_kpa=6.0, friction_angle_deg=35.0, unit_weight_kn_m3=18.9,
         rain_intensity=1.10, terrain_shielding=1.0),
    dict(zone_id="NER-Z04", name="Haflong Hill Rail Section", state="Assam",
         district="Dima Hasao", latitude=25.1640, longitude=93.0170,
         elevation_m=680.0, slope_deg=27.0, soil_depth_m=3.0, porosity=0.45,
         cohesion_kpa=9.0, friction_angle_deg=33.0, unit_weight_kn_m3=18.0,
         rain_intensity=1.25, terrain_shielding=0.85),
    dict(zone_id="NER-Z05", name="Itanagar Capital Approach", state="Arunachal Pradesh",
         district="Papum Pare", latitude=27.0840, longitude=93.6050,
         elevation_m=750.0, slope_deg=29.0, soil_depth_m=2.6, porosity=0.46,
         cohesion_kpa=7.0, friction_angle_deg=34.0, unit_weight_kn_m3=18.2,
         rain_intensity=1.30, terrain_shielding=0.8),
    dict(zone_id="NER-Z06", name="Tupul Rail Embankment", state="Manipur",
         district="Noney", latitude=24.7350, longitude=93.5960,
         elevation_m=900.0, slope_deg=32.0, soil_depth_m=2.2, porosity=0.43,
         cohesion_kpa=5.0, friction_angle_deg=33.0, unit_weight_kn_m3=19.1,
         rain_intensity=1.20, terrain_shielding=0.7),
]

# Instrument complement installed in every zone.
ZONE_SENSOR_PLAN = [
    ("rain_gauge", 1),
    ("soil_moisture", 2),
    ("piezometer", 1),
    ("tiltmeter", 1),
    ("extensometer", 1),
    ("geophone", 1),
]


@dataclass
class SensorState:
    """One physical instrument and its live condition."""

    sensor_id: str
    zone_id: str
    sensor_type: str
    unit: str
    expected_interval_s: int
    depth_m: float                  # installation depth, relevant to subsurface probes
    battery_pct: float
    rssi_dbm: float
    last_value: Optional[float] = None
    drift_bias: float = 0.0
    fault: Optional[str] = None
    fault_ticks_remaining: int = 0
    readings_emitted: int = 0
    readings_expected: int = 0
    comms_failures: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=288))

    def descriptor(self) -> dict:
        return {
            "sensor_id": self.sensor_id,
            "zone_id": self.zone_id,
            "sensor_type": self.sensor_type,
            "unit": self.unit,
            "expected_interval_s": self.expected_interval_s,
            "installation_depth_m": round(self.depth_m, 2),
            "battery_pct": round(self.battery_pct, 1),
            "rssi_dbm": round(self.rssi_dbm, 1),
            "fault_state": self.fault or "nominal",
            "readings_emitted": self.readings_emitted,
            "readings_expected": self.readings_expected,
            "comms_failures": self.comms_failures,
        }


@dataclass
class ZoneState:
    """One monitored slope and its live physical state."""

    zone_id: str
    name: str
    state: str
    district: str
    latitude: float
    longitude: float
    elevation_m: float
    slope_deg: float
    soil_depth_m: float
    porosity: float
    cohesion_kpa: float
    friction_angle_deg: float
    unit_weight_kn_m3: float
    rain_intensity: float
    terrain_shielding: float

    # dynamic state
    rain_regime: int = 0
    rain_rate_mm_hr: float = 0.0
    rain_history: deque = field(default_factory=lambda: deque(maxlen=2016))
    soil_moisture_pct: float = 25.0
    cumulative_displacement_mm: float = 0.0
    cumulative_tilt_deg: float = 0.0
    rainfall_24h_mm: float = 0.0
    rainfall_72h_mm: float = 0.0
    rainfall_7d_mm: float = 0.0
    antecedent_precip_index: float = 0.0
    saturation_ratio: float = 0.0
    pore_pressure_kpa: float = 0.0
    factor_of_safety: float = 3.0
    creep_rate_mm_hr: float = 0.0
    last_risk_level: Optional[str] = None
    surge_ticks_remaining: int = 0
    surge_rate_mm_hr: float = 0.0

    def descriptor(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "state": self.state,
            "district": self.district,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "slope_deg": self.slope_deg,
            "geotechnical": {
                "soil_depth_m": self.soil_depth_m,
                "porosity": self.porosity,
                "cohesion_kpa": self.cohesion_kpa,
                "friction_angle_deg": self.friction_angle_deg,
                "unit_weight_kn_m3": self.unit_weight_kn_m3,
            },
        }

    def conditions(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "rain_regime": RAIN_REGIMES[self.rain_regime],
            "rain_rate_mm_hr": round(self.rain_rate_mm_hr, 2),
            "rainfall_24h_mm": round(self.rainfall_24h_mm, 2),
            "rainfall_72h_mm": round(self.rainfall_72h_mm, 2),
            "rainfall_7d_mm": round(self.rainfall_7d_mm, 2),
            "antecedent_precip_index": round(self.antecedent_precip_index, 2),
            "soil_moisture_pct": round(self.soil_moisture_pct, 2),
            "saturation_ratio": round(self.saturation_ratio, 4),
            "pore_pressure_kpa": round(self.pore_pressure_kpa, 2),
            "factor_of_safety": round(self.factor_of_safety, 3),
            "creep_rate_mm_hr": round(self.creep_rate_mm_hr, 5),
            "cumulative_displacement_mm": round(self.cumulative_displacement_mm, 3),
        }


class SensorFleetSimulator:
    """Advances the physical state of every zone and emits sensor readings."""

    def __init__(self, sim_step_s: int = 300, seed: int = 42,
                 history_readings: int = 288, fault_injection: bool = True,
                 start_time: Optional[datetime] = None):
        self.sim_step_s = int(sim_step_s)
        self.step_hours = self.sim_step_s / 3600.0
        self.seed = int(seed)
        self.history_readings = int(history_readings)
        self.fault_injection = bool(fault_injection)
        self.rng = np.random.default_rng(seed)
        self.tick_count = 0

        self.clock = (start_time or datetime.now(timezone.utc)).replace(microsecond=0)

        # A 7-day rainfall window at the configured cadence.
        self._rain_window = max(int(7 * 86400 / self.sim_step_s), 1)

        self.zones: dict = {}
        self.sensors: dict = {}
        self._build_fleet()

    # -----------------------------------------------------------------
    # Construction
    # -----------------------------------------------------------------
    def _build_fleet(self) -> None:
        for definition in ZONE_DEFINITIONS:
            zone = ZoneState(**definition)
            zone.rain_history = deque(maxlen=self._rain_window)
            zone.soil_moisture_pct = float(self.rng.uniform(20, 32))
            self.zones[zone.zone_id] = zone

            for sensor_type, quantity in ZONE_SENSOR_PLAN:
                for index in range(1, quantity + 1):
                    code = SENSOR_TYPE_CODES[sensor_type]
                    sensor_id = f"{zone.zone_id}-{code}-{index:02d}"
                    if sensor_type == "soil_moisture":
                        depth = 0.3 if index == 1 else round(zone.soil_depth_m * 0.7, 2)
                    elif sensor_type == "piezometer":
                        depth = round(zone.soil_depth_m, 2)
                    else:
                        depth = 0.0
                    self.sensors[sensor_id] = SensorState(
                        sensor_id=sensor_id,
                        zone_id=zone.zone_id,
                        sensor_type=sensor_type,
                        unit=SENSOR_UNITS[sensor_type],
                        expected_interval_s=self.sim_step_s,
                        depth_m=depth,
                        battery_pct=float(self.rng.uniform(58, 100)),
                        rssi_dbm=float(-62 - 18 * (1 - zone.terrain_shielding)),
                        history=deque(maxlen=self.history_readings),
                    )

        # One sensor is seeded with a depleted battery so that the fleet health
        # endpoint has a genuinely degraded unit to report from the first call.
        weakest = f"{ZONE_DEFINITIONS[-1]['zone_id']}-GP-01"
        if weakest in self.sensors:
            self.sensors[weakest].battery_pct = 21.0

    # -----------------------------------------------------------------
    # Environment
    # -----------------------------------------------------------------
    def _advance_rainfall(self, zone: ZoneState) -> None:
        wetting, drying = _seasonal_factors(self.clock.month)

        if zone.surge_ticks_remaining > 0:
            # An operator-injected rainfall surge overrides the regime chain.
            zone.surge_ticks_remaining -= 1
            zone.rain_regime = 3
            zone.rain_rate_mm_hr = zone.surge_rate_mm_hr * float(self.rng.uniform(0.85, 1.15))
        else:
            transitions = RAIN_TRANSITIONS[zone.rain_regime]
            draw = self.rng.random()
            cumulative = 0.0
            for target, base_p in transitions.items():
                if zone.rain_regime == 0 or target == 0:
                    multiplier = wetting if target > zone.rain_regime else drying
                else:
                    multiplier = 1.0
                p = _scale_probability(base_p * multiplier, self.sim_step_s)
                cumulative += p
                if draw < cumulative:
                    zone.rain_regime = target
                    break

            low, high = RAIN_RATE_RANGES[zone.rain_regime]
            if high == 0.0:
                target_rate = 0.0
            else:
                target_rate = float(self.rng.uniform(low, high)) * zone.rain_intensity
            # First-order smoothing, so rainfall ramps rather than switching
            # instantaneously between regimes.
            zone.rain_rate_mm_hr = float(
                max(0.0, 0.72 * zone.rain_rate_mm_hr + 0.28 * target_rate
                    + self.rng.normal(0, 0.4))
            )

        increment_mm = zone.rain_rate_mm_hr * self.step_hours
        zone.rain_history.append(increment_mm)

    def _update_accumulations(self, zone: ZoneState) -> None:
        history = np.fromiter(zone.rain_history, dtype=float)
        steps_24h = max(int(86400 / self.sim_step_s), 1)
        steps_72h = max(int(3 * 86400 / self.sim_step_s), 1)

        zone.rainfall_24h_mm = float(history[-steps_24h:].sum())
        zone.rainfall_72h_mm = float(history[-steps_72h:].sum())
        zone.rainfall_7d_mm = float(history.sum())

        # Same weighting as simulation.physics_slope_model, so the live stream
        # and the training dataset define the index identically.
        zone.antecedent_precip_index = float(
            0.5 * zone.rainfall_7d_mm + 0.35 * zone.rainfall_72h_mm + 0.15 * zone.rainfall_24h_mm
        )

    def _update_stability(self, zone: ZoneState) -> None:
        beta = math.radians(zone.slope_deg)
        phi = math.radians(zone.friction_angle_deg)
        depth = zone.soil_depth_m

        storage_mm = zone.porosity * depth * 1000.0 * WETTING_FRONT_FRACTION
        zone.saturation_ratio = float(
            np.clip(zone.antecedent_precip_index / max(storage_mm, 1e-6), 0.0, 1.0)
        )
        zone.pore_pressure_kpa = float(
            zone.saturation_ratio * GAMMA_WATER * depth * math.cos(beta) ** 2
        )

        normal_stress = zone.unit_weight_kn_m3 * depth * math.cos(beta) ** 2
        resisting = zone.cohesion_kpa + max(normal_stress - zone.pore_pressure_kpa, 0.0) * math.tan(phi)
        driving = zone.unit_weight_kn_m3 * depth * math.sin(beta) * math.cos(beta)
        zone.factor_of_safety = float(resisting / max(driving, 1e-6))

        # Soil moisture relaxes towards the saturation-implied value rather than
        # tracking it instantly, which reproduces the observed lag between a
        # rainfall peak and the soil moisture response.
        residual_pct = 18.0
        target_moisture = residual_pct + (zone.porosity * 100.0 - residual_pct) * zone.saturation_ratio
        relaxation = min(0.12 * (self.sim_step_s / 300.0), 1.0)
        zone.soil_moisture_pct = float(
            np.clip(zone.soil_moisture_pct + relaxation * (target_moisture - zone.soil_moisture_pct),
                    0.0, 100.0)
        )

        # Creep accelerates as the Factor of Safety approaches one. Below unity
        # the slope is mechanically unstable and displacement runs away, which
        # is exactly the signature a deformation sensor is installed to catch.
        margin = zone.factor_of_safety - 1.0
        zone.creep_rate_mm_hr = float(0.05 * math.exp(-6.0 * margin))
        zone.cumulative_displacement_mm += zone.creep_rate_mm_hr * self.step_hours
        zone.cumulative_tilt_deg = zone.cumulative_displacement_mm * 0.05

    # -----------------------------------------------------------------
    # Sensors
    # -----------------------------------------------------------------
    def _true_value(self, sensor: SensorState, zone: ZoneState) -> float:
        kind = sensor.sensor_type
        if kind == "rain_gauge":
            return zone.rain_rate_mm_hr
        if kind == "soil_moisture":
            # A shallow probe responds faster and more strongly than a deep one.
            shallow = sensor.depth_m <= 0.5
            factor = 1.08 if shallow else 0.88
            return zone.soil_moisture_pct * factor
        if kind == "piezometer":
            return zone.pore_pressure_kpa
        if kind == "tiltmeter":
            return zone.cumulative_tilt_deg
        if kind == "extensometer":
            return zone.cumulative_displacement_mm
        if kind == "geophone":
            # Background microseismic energy plus an activity term that rises
            # with creep rate.
            return 0.04 + 12.0 * zone.creep_rate_mm_hr
        return 0.0

    def _update_fault(self, sensor: SensorState) -> Optional[str]:
        """Advances the fault state machine. Returns a fault name when a new
        fault begins, so the caller can publish a fault event."""
        if sensor.fault is not None:
            sensor.fault_ticks_remaining -= 1
            if sensor.fault_ticks_remaining <= 0:
                if sensor.fault == "calibration_drift":
                    sensor.drift_bias = 0.0
                sensor.fault = None
            return None

        if not self.fault_injection:
            return None

        onset = _scale_probability(FAULT_ONSET_PROBABILITY, self.sim_step_s)
        if self.rng.random() >= onset:
            return None

        names = list(FAULT_PROFILES)
        weights = np.array([FAULT_PROFILES[n]["weight"] for n in names], dtype=float)
        chosen = names[int(self.rng.choice(len(names), p=weights / weights.sum()))]
        profile = FAULT_PROFILES[chosen]
        sensor.fault = chosen
        sensor.fault_ticks_remaining = int(
            self.rng.integers(profile["min_ticks"], profile["max_ticks"] + 1)
        )
        if chosen == "calibration_drift":
            sensor.drift_bias = 0.0
        return chosen

    def _apply_fault(self, sensor: SensorState, value: float, noise_std: float) -> Optional[float]:
        """Returns the reported value, or None when the sensor fails to report."""
        if sensor.fault == "comms_dropout":
            sensor.comms_failures += 1
            return None
        if sensor.fault == "stuck_reading" and sensor.last_value is not None:
            return sensor.last_value
        if sensor.fault == "calibration_drift":
            # Bias accumulates towards roughly six noise standard deviations,
            # which is well inside the plausible range and therefore only
            # detectable by the drift test, not by a bounds check.
            sensor.drift_bias += noise_std * 0.12
            return value + sensor.drift_bias
        if sensor.fault == "noise_burst":
            return value + float(self.rng.normal(0, noise_std * 8.0))
        return value

    def _emit_reading(self, sensor: SensorState, zone: ZoneState) -> Optional[dict]:
        sensor.readings_expected += 1

        true_value = self._true_value(sensor, zone)
        noise_std = SENSOR_NOISE_STD[sensor.sensor_type]
        measured = true_value + float(self.rng.normal(0, noise_std))

        reported = self._apply_fault(sensor, measured, noise_std)
        if reported is None:
            return None

        if sensor.sensor_type in ("rain_gauge", "soil_moisture", "geophone"):
            reported = max(reported, 0.0)

        # Battery discharge and link quality.
        drain = 0.0006 * (self.sim_step_s / 300.0)
        if sensor.fault == "comms_dropout":
            drain *= 2.0
        sensor.battery_pct = float(max(sensor.battery_pct - drain, 0.0))
        base_rssi = -62 - 18 * (1 - zone.terrain_shielding)
        rain_attenuation = min(zone.rain_rate_mm_hr * 0.18, 12.0)
        sensor.rssi_dbm = float(
            np.clip(base_rssi - rain_attenuation + self.rng.normal(0, 2.0), -110, -40)
        )

        sensor.last_value = reported
        sensor.readings_emitted += 1

        reading = {
            "sensor_id": sensor.sensor_id,
            "zone_id": sensor.zone_id,
            "sensor_type": sensor.sensor_type,
            "timestamp": self.clock.isoformat(),
            "value": round(float(reported), 4),
            "unit": sensor.unit,
            "battery_pct": round(sensor.battery_pct, 1),
            "rssi_dbm": round(sensor.rssi_dbm, 1),
            "expected_interval_s": sensor.expected_interval_s,
        }
        sensor.history.append(reading)
        return reading

    # -----------------------------------------------------------------
    # Ticking
    # -----------------------------------------------------------------
    def tick(self, emit: bool = True) -> dict:
        """Advances the simulated clock by one step.

        Returns a dictionary with the readings produced and the fault
        transitions that occurred, both of which the service publishes on the
        stream bus.
        """
        self.clock = self.clock + timedelta(seconds=self.sim_step_s)
        self.tick_count += 1

        readings = []
        faults = []

        for zone in self.zones.values():
            self._advance_rainfall(zone)
            self._update_accumulations(zone)
            self._update_stability(zone)

        for sensor in self.sensors.values():
            new_fault = self._update_fault(sensor)
            if new_fault is not None:
                faults.append({
                    "sensor_id": sensor.sensor_id,
                    "zone_id": sensor.zone_id,
                    "sensor_type": sensor.sensor_type,
                    "fault": new_fault,
                    "expected_duration_ticks": sensor.fault_ticks_remaining,
                    "detected_at": self.clock.isoformat(),
                })
            if not emit:
                continue
            reading = self._emit_reading(sensor, zone)
            if reading is not None:
                readings.append(reading)

        return {
            "simulated_time": self.clock.isoformat(),
            "tick": self.tick_count,
            "readings": readings,
            "faults": faults,
        }

    def warm_up(self, days: float, max_steps: int = 20000) -> int:
        """Runs the simulation forward before the service starts serving, so
        that rainfall accumulations, saturation and the reading history are
        already populated on the first request rather than starting from zero.

        The simulated clock is rewound by the warm-up duration first, so that
        the service begins serving at approximately the current wall-clock
        time.
        """
        steps = min(int(days * 86400 / self.sim_step_s), max_steps)
        if steps <= 0:
            return 0

        self.clock = self.clock - timedelta(seconds=steps * self.sim_step_s)
        emit_from = max(steps - self.history_readings, 0)
        for index in range(steps):
            self.tick(emit=index >= emit_from)
        return steps

    # -----------------------------------------------------------------
    # Operator controls, used by the simulation endpoints
    # -----------------------------------------------------------------
    def inject_rainfall_surge(self, zone_id: str, rate_mm_hr: float,
                              duration_minutes: float) -> dict:
        zone = self.zones[zone_id]
        ticks = max(int(duration_minutes * 60 / self.sim_step_s), 1)
        zone.surge_ticks_remaining = ticks
        zone.surge_rate_mm_hr = float(rate_mm_hr)
        return {
            "zone_id": zone_id,
            "rate_mm_hr": zone.surge_rate_mm_hr,
            "duration_minutes": duration_minutes,
            "ticks": ticks,
        }

    def inject_sensor_fault(self, sensor_id: str, fault: str,
                            duration_ticks: Optional[int] = None) -> dict:
        sensor = self.sensors[sensor_id]
        if fault not in FAULT_PROFILES:
            raise KeyError(fault)
        profile = FAULT_PROFILES[fault]
        sensor.fault = fault
        sensor.fault_ticks_remaining = int(duration_ticks or profile["min_ticks"] * 2)
        if fault == "calibration_drift":
            sensor.drift_bias = 0.0
        return {
            "sensor_id": sensor_id,
            "fault": fault,
            "duration_ticks": sensor.fault_ticks_remaining,
        }

    def clear_faults(self) -> int:
        cleared = 0
        for sensor in self.sensors.values():
            if sensor.fault is not None:
                sensor.fault = None
                sensor.fault_ticks_remaining = 0
                sensor.drift_bias = 0.0
                cleared += 1
        for zone in self.zones.values():
            zone.surge_ticks_remaining = 0
        return cleared

    # -----------------------------------------------------------------
    # Accessors
    # -----------------------------------------------------------------
    def zone_ids(self) -> list:
        return list(self.zones)

    def sensors_in_zone(self, zone_id: str) -> list:
        return [s for s in self.sensors.values() if s.zone_id == zone_id]

    def latest_reading(self, sensor_id: str) -> Optional[dict]:
        history = self.sensors[sensor_id].history
        return history[-1] if history else None

    def readings(self, sensor_id: str, limit: int = 100,
                 since: Optional[str] = None) -> list:
        history = list(self.sensors[sensor_id].history)
        if since:
            history = [r for r in history if r["timestamp"] >= since]
        return history[-limit:]


if __name__ == "__main__":
    sim = SensorFleetSimulator(sim_step_s=300, seed=42)
    steps = sim.warm_up(days=7.0)
    print(f"Warm-up complete: {steps} simulated steps, clock at {sim.clock.isoformat()}")
    print(f"Fleet: {len(sim.zones)} zones, {len(sim.sensors)} sensors\n")

    for zone in sim.zones.values():
        conditions = zone.conditions()
        print(f"{zone.zone_id} {zone.name:32s} "
              f"FS={conditions['factor_of_safety']:6.3f} "
              f"m={conditions['saturation_ratio']:.3f} "
              f"r24={conditions['rainfall_24h_mm']:7.2f} "
              f"r7d={conditions['rainfall_7d_mm']:8.2f} "
              f"regime={conditions['rain_regime']}")

    result = sim.tick()
    print(f"\nOne tick produced {len(result['readings'])} readings "
          f"at {result['simulated_time']}")
    for reading in result["readings"][:6]:
        print(f"  {reading['sensor_id']:18s} {reading['sensor_type']:14s} "
              f"{reading['value']:9.3f} {reading['unit']}")
