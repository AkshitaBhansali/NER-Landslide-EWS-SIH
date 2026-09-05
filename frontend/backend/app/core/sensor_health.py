"""Sensor health scoring.

Weights are taken from the data pipeline so the console and the pipeline can
never disagree about what "health 62" means:

    completeness 0.25 | validity 0.25 | stability 0.20 | noise 0.15 | comms 0.15

The point of this module is the distinction the whole platform depends on:
a HIGH RISK reading and an UNRELIABLE SENSOR look identical in raw data and must
never be treated the same. Health is computed independently of risk and travels
with it, so the alert engine can say "high risk, low confidence — verify" instead
of either crying wolf or staying silent.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

WEIGHTS = {
    "completeness": 0.25,
    "validity": 0.25,
    "stability": 0.20,
    "noise": 0.15,
    "comms": 0.15,
}

# Physically plausible ranges per sensor type. Outside these, a reading is invalid.
VALID_RANGES = {
    "RAIN_GAUGE": (0.0, 120.0),        # mm/h
    "SOIL_MOISTURE": (0.0, 100.0),     # % VWC
    "PIEZOMETER": (0.0, 200.0),        # kPa
    "TILTMETER": (-15.0, 15.0),        # degrees
    "EXTENSOMETER": (0.0, 500.0),      # mm
    "GEOPHONE": (0.0, 140.0),          # dB
    "WEATHER_STATION": (-15.0, 55.0),  # deg C
}

UNITS = {
    "RAIN_GAUGE": "mm/h",
    "SOIL_MOISTURE": "% VWC",
    "PIEZOMETER": "kPa",
    "TILTMETER": "\u00b0",
    "EXTENSOMETER": "mm",
    "GEOPHONE": "dB",
    "WEATHER_STATION": "\u00b0C",
}

LABELS = {
    "RAIN_GAUGE": "Rain gauge",
    "SOIL_MOISTURE": "Soil moisture",
    "PIEZOMETER": "Piezometer",
    "TILTMETER": "Tiltmeter",
    "EXTENSOMETER": "Extensometer",
    "GEOPHONE": "Geophone",
    "WEATHER_STATION": "Weather station",
}


@dataclass
class HealthResult:
    score: float                  # 0-100
    status: str                   # ONLINE | DEGRADED | OFFLINE  (Healthy/Degraded/Failed)
    sub_scores: dict[str, float]
    note: str | None


def _completeness(received: int, expected: int) -> float:
    if expected <= 0:
        return 1.0
    return max(0.0, min(1.0, received / expected))


def _validity(values: list[float], sensor_type: str) -> float:
    if not values:
        return 0.0
    lo, hi = VALID_RANGES.get(sensor_type, (-1e9, 1e9))
    ok = sum(1 for v in values if lo <= v <= hi)
    return ok / len(values)


def _stability(values: list[float]) -> float:
    """Penalises monotonic drift — a probe walking away from truth still 'reports'."""
    if len(values) < 4:
        return 1.0
    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = statistics.fmean(values)
    denom = sum((i - mean_x) ** 2 for i in range(n)) or 1.0
    slope = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / denom
    spread = (max(values) - min(values)) or 1.0
    drift = abs(slope) * n / spread
    return max(0.0, min(1.0, 1.0 - drift))


def _noise(values: list[float]) -> float:
    """High-frequency jitter relative to the signal level."""
    if len(values) < 3:
        return 1.0
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    level = max(abs(statistics.fmean(values)), 1e-6)
    ratio = statistics.fmean(diffs) / level
    return max(0.0, min(1.0, 1.0 - ratio))


def _comms(battery_pct: float, rssi_dbm: float) -> float:
    batt = max(0.0, min(1.0, battery_pct / 100.0))
    # -120 dBm unusable, -58 dBm excellent
    link = max(0.0, min(1.0, (rssi_dbm + 120.0) / 62.0))
    return round(0.5 * batt + 0.5 * link, 3)


def compute_health(
    *,
    sensor_type: str,
    values: list[float],
    expected_samples: int,
    battery_pct: float,
    rssi_dbm: float,
    last_seen: datetime,
    expected_interval_s: int = 900,
    now: datetime | None = None,
) -> HealthResult:
    now = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    subs = {
        "completeness": round(_completeness(len(values), expected_samples), 3),
        "validity": round(_validity(values, sensor_type), 3),
        "stability": round(_stability(values), 3),
        "noise": round(_noise(values), 3),
        "comms": _comms(battery_pct, rssi_dbm),
    }
    score = round(sum(subs[k] * w for k, w in WEIGHTS.items()) * 100, 1)

    # A silent sensor is a failed sensor regardless of how good its last data looked.
    silence = now - last_seen
    missed_intervals = silence / timedelta(seconds=max(expected_interval_s, 1))
    if missed_intervals >= 8:
        status = "OFFLINE"
        score = min(score, 20.0)
    elif missed_intervals >= 3:
        status = "DEGRADED"
        score = min(score, 55.0)
    elif score >= 75:
        status = "ONLINE"
    elif score >= 45:
        status = "DEGRADED"
    else:
        status = "OFFLINE"

    note = None
    if status == "OFFLINE" and missed_intervals >= 8:
        note = f"No uplink for {int(silence.total_seconds() // 60)} min \u2014 dispatch a field check."
    elif subs["stability"] < 0.6:
        note = "Drift detected \u2014 recalibration recommended."
    elif battery_pct < 25:
        note = "Battery below 25% \u2014 schedule replacement."
    elif rssi_dbm < -105:
        note = "Weak uplink \u2014 check gateway line of sight."

    return HealthResult(score=score, status=status, sub_scores=subs, note=note)


def zone_confidence(sensor_health_scores: list[float], sensor_count_target: int = 4) -> float:
    """Confidence in a zone's risk score, given the sensors that actually reported.

    Two independent penalties: mean health of the sensors present, and how many are
    present at all. A zone with one perfect sensor is not as trustworthy as a zone
    with four good ones, and the number should say so.
    """
    if not sensor_health_scores:
        return 0.0
    mean_health = sum(sensor_health_scores) / len(sensor_health_scores)
    coverage = min(1.0, len(sensor_health_scores) / max(sensor_count_target, 1))
    return round(mean_health * (0.55 + 0.45 * coverage), 1)
