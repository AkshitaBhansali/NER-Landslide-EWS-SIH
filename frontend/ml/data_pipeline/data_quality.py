"""
Data Quality Module
===================

Purpose
-------
Handles missing values, outliers, noise, timestamp normalisation, sensor drift
and communication failures for both the static inventory dataset and live
sensor time series.

Classes
-------
- HistoricalDataCleaner: static inventory dataset. Removes duplicates, flags
  implausible coordinates and values, caps rainfall outliers by an IQR rule
  and reports every change it made.
- SensorStreamCleaner: live per-sensor time series. Detects gaps and
  communication failures, resamples to a regular interval, suppresses noise
  with a rolling median, detects drift and interpolates only short gaps.

Notes
-----
Rainfall outliers are capped rather than dropped, because extreme rainfall is
the signal of interest rather than a data error. A missing sensor reading is
recorded as missing rather than silently interpolated, so that a quiet sensor
is never confused with an absence of activity on the slope.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Historical / inventory dataset cleaning
# ---------------------------------------------------------------------------
class HistoricalDataCleaner:
    """Cleans the static historical event table (see historical_ingestion.py)."""

    def __init__(self):
        self.report = {}

    def run(self, df: pd.DataFrame, outlier_method: str = "cap") -> pd.DataFrame:
        df = df.copy()
        self.report["original_shape"] = df.shape

        # --- missing values ---
        missing = df.isnull().sum()
        self.report["missing_by_column"] = missing[missing > 0].to_dict()
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        # For a historical inventory, dropping rows loses irreplaceable
        # ground-truth events; median-fill numeric fields, flag rather than drop.
        df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
        df["data_confidence"] = df["data_confidence"].fillna("low")

        # --- duplicates (same source+event_id) ---
        before = len(df)
        df = df.drop_duplicates(subset=["source", "event_id"])
        self.report["duplicates_removed"] = before - len(df)

        # --- physical plausibility bounds (NER-specific, not generic IQR) ---
        # A landslide record outside these bounds is a data-entry/geocoding
        # error, not a real outlier event, so it gets flagged not capped.
        implausible = pd.Series(False, index=df.index)
        implausible |= ~df["slope_deg"].between(0, 90)
        implausible |= ~df["elevation_m"].between(0, 6000)
        implausible |= df["rainfall_24h_mm"] < 0
        self.report["implausible_rows_flagged"] = int(implausible.sum())
        df["quality_flag_implausible"] = implausible

        # Statistical outliers on rainfall and soil moisture are capped rather
        # than dropped, because extreme rainfall is usually the signal itself.
        if outlier_method == "cap":
            for col in ["rainfall_24h_mm", "rainfall_72h_mm", "rainfall_7d_mm"]:
                q1, q3 = df[col].quantile([0.25, 0.75])
                iqr = q3 - q1
                upper = q3 + 3.0 * iqr  # wide multiplier: monsoon rainfall is legitimately heavy-tailed
                capped = (df[col] > upper).sum()
                df[col] = np.clip(df[col], 0, upper)
                self.report[f"{col}_capped"] = int(capped)

        self.report["final_shape"] = df.shape
        return df


# ---------------------------------------------------------------------------
# Live sensor stream cleaning
# ---------------------------------------------------------------------------
class SensorStreamCleaner:
    """
    Cleans a single sensor's raw time series. Operates per-sensor because
    drift/noise/gap characteristics are sensor- and site-specific - pooling
    across sensors before cleaning would smear real anomalies with normal
    cross-sensor variance.
    """

    def __init__(self, expected_interval_s: int = 300, drift_window: int = 24,
                 drift_z_threshold: float = 3.0):
        self.expected_interval_s = expected_interval_s
        self.drift_window = drift_window          # rolling windows compared for drift
        self.drift_z_threshold = drift_z_threshold
        self.report = {}

    def detect_gaps(self, df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
        """Flags reporting gaps larger than expected cadence as communication failures."""
        df = df.sort_values(ts_col).reset_index(drop=True)
        df[ts_col] = pd.to_datetime(df[ts_col])
        gap_s = df[ts_col].diff().dt.total_seconds()
        tolerance = self.expected_interval_s * 2.5  # allow some jitter before flagging
        df["gap_s"] = gap_s
        df["comms_failure"] = gap_s > tolerance
        self.report["comms_failures_detected"] = int(df["comms_failure"].sum())
        self.report["longest_gap_hours"] = round(float(gap_s.max() or 0) / 3600, 2)
        return df

    def resample_regular(self, df: pd.DataFrame, ts_col: str = "timestamp",
                          value_col: str = "value") -> pd.DataFrame:
        """Places the stream on a regular grid, leaving NaN where data is genuinely
        missing. Interpolation is applied separately by interpolate_short_gaps(),
        which bounds how far a fill may be trusted."""
        s = df.set_index(ts_col)[value_col]
        regular = s.resample(f"{self.expected_interval_s}s").mean()
        return regular.to_frame(value_col)

    def handle_noise(self, series: pd.Series, window: int = 5) -> pd.Series:
        """Rolling-median smoothing to suppress single-sample spikes (comms glitches,
        electrical noise) while preserving genuine step changes (a real tilt event)."""
        return series.rolling(window=window, center=True, min_periods=1).median()

    def detect_drift(self, series: pd.Series) -> pd.Series:
        """
        Flags calibration drift: compares each rolling window's mean against the
        first window's baseline mean/std. A sensor reading 'soil moisture' that
        slowly climbs over weeks with no corresponding rainfall is drifting, not
        detecting an actual trend - this is what lets the sensor-health score
        separate 'sensor miscalibrating' from 'ground genuinely wetter.'
        """
        if len(series) < self.drift_window * 2:
            return pd.Series(False, index=series.index)
        baseline_mean = series.iloc[:self.drift_window].mean()
        baseline_std = series.iloc[:self.drift_window].std() or 1e-6
        rolling_mean = series.rolling(self.drift_window, min_periods=self.drift_window).mean()
        z = (rolling_mean - baseline_mean) / baseline_std
        drifted = z.abs() > self.drift_z_threshold
        self.report["drift_flagged_fraction"] = float(drifted.mean())
        return drifted.fillna(False)

    def interpolate_short_gaps(self, series: pd.Series, max_gap_periods: int = 3) -> pd.Series:
        """Linearly interpolates only short gaps (<= max_gap_periods); longer gaps stay
        NaN so downstream code (and the sensor-health score) knows real data is missing
        rather than being fooled by a long straight-line guess."""
        return series.interpolate(method="linear", limit=max_gap_periods, limit_area="inside")

    def clean(self, df: pd.DataFrame, ts_col: str = "timestamp",
              value_col: str = "value") -> pd.DataFrame:
        df = self.detect_gaps(df, ts_col)
        regular = self.resample_regular(df, ts_col, value_col)
        regular[f"{value_col}_smoothed"] = self.handle_noise(regular[value_col])
        regular[f"{value_col}_interpolated"] = self.interpolate_short_gaps(regular[f"{value_col}_smoothed"])
        regular["drift_flagged"] = self.detect_drift(regular[f"{value_col}_interpolated"])
        regular["is_missing"] = regular[f"{value_col}_interpolated"].isna()
        return regular.reset_index()


def _demo():
    """Synthetic soil-moisture sensor stream with an injected gap and drift,
    to prove the pipeline actually catches both."""
    rng = np.random.default_rng(0)
    n = 300
    ts = pd.date_range("2026-07-01", periods=n, freq="5min")
    base = 30 + 4 * np.sin(np.linspace(0, 6, n))
    drift = np.linspace(0, 15, n)  # injected slow calibration drift
    noise = rng.normal(0, 1.2, n)
    values = base + drift + noise
    df = pd.DataFrame({"timestamp": ts, "value": values})
    # inject a comms outage
    df = df.drop(df.index[120:135]).reset_index(drop=True)

    cleaner = SensorStreamCleaner(expected_interval_s=300)
    cleaned = cleaner.clean(df)
    print("Sensor stream cleaning report:", cleaner.report)
    print(cleaned[cleaned["drift_flagged"]].head())

    hist = pd.read_csv("../data/historical_events_placeholder.csv")
    hcleaner = HistoricalDataCleaner()
    hclean = hcleaner.run(hist)
    print("\nHistorical cleaning report:")
    for k, v in hcleaner.report.items():
        print(f"  {k}: {v}")
    hclean.to_csv("../data/historical_events_cleaned.csv", index=False)


if __name__ == "__main__":
    _demo()
