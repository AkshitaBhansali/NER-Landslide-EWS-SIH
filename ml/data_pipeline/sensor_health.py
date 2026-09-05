"""
Sensor Health Scoring
=====================

Purpose
-------
Produces a per-sensor confidence signal so that the platform can distinguish
high landslide risk from low sensor confidence. A piezometer reporting a pore
pressure spike may indicate a destabilising slope, or a loose, waterlogged or
low-battery sensor returning invalid data. The alert engine and the dashboard
both attach this signal to every risk prediction.

Composite score
---------------
A 0-100 score computed from five independent sub-scores:

1. completeness: fraction of expected readings actually received.
2. validity: fraction of readings within physically plausible bounds.
3. stability: inverse of drift severity, from data_quality.SensorStreamCleaner.
4. noise: signal noise against the expected specification of the sensor type.
5. comms: communication uptime from battery level, RSSI and gap history.

Weights are configurable per sensor type, because a rain gauge missing a
single reading is less consequential than a piezometer missing a reading
immediately before a forecast rainfall peak.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# Physically plausible ranges per sensor type - used for the validity sub-score.
# Anything outside this range is either a fault or a genuinely extreme event;
# validity scoring treats it as "can't trust this single reading" either way.
PLAUSIBLE_RANGES = {
    "rain_gauge":      (0.0, 300.0),      # mm/hr, extreme NER cloudburst ceiling
    "soil_moisture":   (0.0, 100.0),      # % volumetric
    "piezometer":      (-20.0, 500.0),    # kPa pore pressure
    "tiltmeter":       (-45.0, 45.0),     # degrees
    "extensometer":    (-500.0, 500.0),   # mm displacement
    "geophone":        (0.0, 50.0),       # mm/s ground velocity
}

DEFAULT_WEIGHTS = dict(completeness=0.25, validity=0.25, stability=0.20, noise=0.15, comms=0.15)

# Expected noise (1-sigma) per sensor type from typical outdoor field-sensor
# datasheets - used as the reference for the noise sub-score instead of
# comparing against the signal's own variance (which breaks down whenever
# the true underlying signal is nearly flat, as it often is for a stable
# slope with no rain).
EXPECTED_NOISE_STD = {
    "rain_gauge": 0.5,       # mm
    "soil_moisture": 1.0,    # %
    "piezometer": 2.0,       # kPa
    "tiltmeter": 0.05,       # deg
    "extensometer": 0.3,     # mm
    "geophone": 0.3,         # mm/s
}


@dataclass
class SensorHealthResult:
    sensor_id: str
    sensor_type: str
    completeness: float
    validity: float
    stability: float
    noise: float
    comms: float
    health_score: float
    status: str
    notes: list = field(default_factory=list)


class SensorHealthScorer:
    def __init__(self, weights: dict | None = None):
        self.weights = weights or DEFAULT_WEIGHTS

    # --- sub-scores, each returns 0-100 ---
    def _completeness_score(self, n_received: int, n_expected: int) -> float:
        if n_expected <= 0:
            return 0.0
        return float(np.clip(100.0 * n_received / n_expected, 0, 100))

    def _validity_score(self, values: pd.Series, sensor_type: str) -> float:
        lo, hi = PLAUSIBLE_RANGES.get(sensor_type, (-np.inf, np.inf))
        valid = values.dropna().between(lo, hi)
        if len(valid) == 0:
            return 0.0
        return float(100.0 * valid.mean())

    def _stability_score(self, drift_flagged: pd.Series) -> float:
        if len(drift_flagged) == 0:
            return 100.0
        drift_fraction = float(drift_flagged.mean())
        return float(np.clip(100.0 * (1 - drift_fraction), 0, 100))

    def _noise_score(self, raw: pd.Series, smoothed: pd.Series, sensor_type: str) -> float:
        """
        Compares observed residual noise (raw - smoothed) against the
        expected 1-sigma noise for that sensor type (EXPECTED_NOISE_STD),
        not against the signal's own variance - a sensor sitting on a
        stable slope with a near-flat true reading should still score
        well here, since the reference point is the sensor's datasheet
        noise floor, not how much the ground happens to be moving.
        """
        residual = (raw - smoothed).dropna()
        if len(residual) == 0:
            return 100.0
        expected = EXPECTED_NOISE_STD.get(sensor_type, max(residual.std(), 1e-6))
        ratio = residual.std() / max(expected, 1e-6)
        # ratio <= 1 (at or below datasheet noise floor) => full marks;
        # ratio >= 4x datasheet floor => essentially unusable
        return float(np.clip(100.0 * (1 - (ratio - 1) / 3), 0, 100))

    def _comms_score(self, comms_failures: int, n_readings: int,
                      battery_pct: float | None, hours_since_last: float | None) -> float:
        failure_rate = comms_failures / max(n_readings, 1)
        score = 100.0 * (1 - min(failure_rate * 3, 1.0))  # each failure penalized 3x its raw rate
        if battery_pct is not None:
            score = score * np.clip(0.5 + battery_pct / 200.0, 0.5, 1.0)  # low battery drags score down
        if hours_since_last is not None and hours_since_last > 6:
            score *= 0.3  # sensor gone quiet for >6h is close to "offline" regardless of history
        return float(np.clip(score, 0, 100))

    def score(self, sensor_id: str, sensor_type: str, cleaned_stream: pd.DataFrame,
              n_expected: int, comms_failures: int, battery_pct: float | None = None,
              hours_since_last: float | None = None,
              value_col: str = "value") -> SensorHealthResult:
        n_received = int((~cleaned_stream[f"{value_col}_interpolated"].isna()).sum()) \
            if f"{value_col}_interpolated" in cleaned_stream else len(cleaned_stream.dropna(subset=[value_col]))

        completeness = self._completeness_score(n_received, n_expected)
        validity = self._validity_score(cleaned_stream[value_col], sensor_type)
        stability = self._stability_score(cleaned_stream.get("drift_flagged", pd.Series(dtype=bool)))
        noise = self._noise_score(cleaned_stream[value_col],
                                   cleaned_stream.get(f"{value_col}_smoothed", cleaned_stream[value_col]),
                                   sensor_type)
        comms = self._comms_score(comms_failures, len(cleaned_stream), battery_pct, hours_since_last)

        w = self.weights
        health = (w["completeness"] * completeness + w["validity"] * validity +
                  w["stability"] * stability + w["noise"] * noise + w["comms"] * comms)

        notes = []
        if completeness < 60:
            notes.append("Significant missing data - treat predictions from this sensor with caution")
        if validity < 80:
            notes.append("Readings frequently outside physically plausible range - check calibration/wiring")
        if stability < 70:
            notes.append("Drift detected - schedule recalibration")
        if comms < 50:
            notes.append("Poor/interrupted communication - verify connectivity, battery, mounting")

        if health >= 80:
            status = "Healthy"
        elif health >= 60:
            status = "Degraded"
        elif health >= 30:
            status = "Unreliable"
        else:
            status = "Offline/Unusable"

        return SensorHealthResult(sensor_id, sensor_type, round(completeness, 1),
                                   round(validity, 1), round(stability, 1), round(noise, 1),
                                   round(comms, 1), round(health, 1), status, notes)


def score_fleet(streams: dict, expected_counts: dict, comms_failures: dict,
                 sensor_types: dict, battery: dict | None = None) -> pd.DataFrame:
    """Scores a whole fleet of sensors at once; returns a table ready for the
    dashboard's sensor-health panel and for gating which readings the ML/alert
    layer should trust."""
    scorer = SensorHealthScorer()
    rows = []
    for sid, stream in streams.items():
        r = scorer.score(sid, sensor_types[sid], stream, expected_counts[sid],
                          comms_failures.get(sid, 0),
                          battery_pct=(battery or {}).get(sid))
        rows.append(vars(r))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from data_quality import SensorStreamCleaner

    rng = np.random.default_rng(1)
    n = 288  # a day at 5-min cadence
    ts = pd.date_range("2026-07-15", periods=n, freq="5min")

    # sensor A: healthy
    healthy = pd.DataFrame({"timestamp": ts, "value": 30 + rng.normal(0, 1, n)})
    # sensor B: drifting + noisy + some gaps
    drifting = pd.DataFrame({"timestamp": ts, "value": 30 + np.linspace(0, 20, n) + rng.normal(0, 4, n)})
    drifting = drifting.drop(drifting.index[100:110]).reset_index(drop=True)

    cleaner = SensorStreamCleaner(expected_interval_s=300)
    clean_a = cleaner.clean(healthy)
    fails_a = cleaner.report["comms_failures_detected"]
    clean_b = cleaner.clean(drifting)
    fails_b = cleaner.report["comms_failures_detected"]

    fleet = score_fleet(
        streams={"SM-001": clean_a, "SM-002": clean_b},
        expected_counts={"SM-001": n, "SM-002": n},
        comms_failures={"SM-001": fails_a, "SM-002": fails_b},
        sensor_types={"SM-001": "soil_moisture", "SM-002": "soil_moisture"},
        battery={"SM-001": 92, "SM-002": 41},
    )
    print(fleet.to_string(index=False))
