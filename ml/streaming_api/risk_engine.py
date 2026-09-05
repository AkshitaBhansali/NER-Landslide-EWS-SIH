"""
Live Zone Risk Engine
=====================

Purpose
-------
Turns the live physical state of a zone into the platform output contract
(`risk_score`, `risk_level`, `probability`, `contributing_factors`) by calling
the model trained in `ml/train_risk_model.py`. This is the online counterpart
of the offline training script: the same five observable features, the same
`risk_output_schema()` function, and therefore the same contract the dashboard
already consumes.

Two independent assessments
---------------------------
Every zone is assessed twice on each refresh:

1. The trained classifier, which learned the relationship between rainfall,
   slope and failure from the simulated scenario dataset.
2. The infinite-slope Factor of Safety, computed directly from the zone's
   live saturation state.

They are reported side by side rather than blended into a single number,
because they fail in different ways. The classifier generalises from a
distribution that may not contain a given zone's parameters, while the Factor
of Safety is only as good as the geotechnical survey behind its cohesion and
friction values. The published `alert_level` takes the more severe of the two,
which is the correct bias for an early warning system: a disagreement between
the statistical and the mechanical view is a reason to warn, not a reason to
average.

Sensor confidence
-----------------
The alert carries the aggregate sensor health of the zone. A prediction is not
withheld when confidence is low, because withholding an alert on the basis of
instrument condition is the wrong failure mode. It is labelled instead, so the
operator sees both the risk and the reliability of the evidence behind it.

Fallback
--------
If `data/risk_model.joblib` is missing, the engine falls back to deriving risk
from the Factor of Safety alone and marks the source as `physics_fallback`, so
the service starts and streams even before the training script has been run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]   # <repo>/ml
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.train_risk_model import OBSERVABLE_FEATURES, risk_output_schema   # noqa: E402
from simulation.physics_slope_model import risk_level_from_fs            # noqa: E402

# Severity ordering used to combine the statistical and mechanical views.
RISK_ORDER = {"Low": 0, "Moderate": 1, "High": 2, "Critical": 3}

# Risk score bands, identical to those in ml.train_risk_model.risk_output_schema
# so the fallback path and the model path label scores the same way.
SCORE_BANDS = ((70.0, "Critical"), (45.0, "High"), (20.0, "Moderate"))


def _level_from_score(score: float) -> str:
    for threshold, level in SCORE_BANDS:
        if score >= threshold:
            return level
    return "Low"


def _score_from_fs(fs: float) -> float:
    """Maps a Factor of Safety to a 0-100 score aligned with the risk bands.

    The anchor points are the band edges of `risk_level_from_fs`: FS 1.0 maps
    to 70 (the Critical threshold), FS 1.3 to 45 (High), FS 1.8 to 20
    (Moderate), with linear interpolation between and saturation outside.
    """
    if fs <= 0.7:
        return 100.0
    if fs <= 1.0:
        return 70.0 + (1.0 - fs) / 0.3 * 30.0
    if fs <= 1.3:
        return 45.0 + (1.3 - fs) / 0.3 * 25.0
    if fs <= 1.8:
        return 20.0 + (1.8 - fs) / 0.5 * 25.0
    if fs >= 3.0:
        return 0.0
    return 20.0 * (3.0 - fs) / 1.2


class ZoneRiskEngine:
    """Produces the risk record published for each zone."""

    def __init__(self, model_dir: Optional[str] = None):
        # The shared data tree lives at <repo>/data/ml, not <repo>/ml/data: the
        # trained model and the historical dataset are consumed by both this
        # streaming service and the platform backend, so neither owns the copy.
        self.model_dir = (Path(model_dir) if model_dir
                          else _REPO_ROOT.parent / "data" / "ml")
        self.model = None
        self.feature_importance: Optional[pd.Series] = None
        self.model_name = "physics_fallback"
        self.source = "physics_fallback"
        self.metrics: dict = {}
        self.load_error: Optional[str] = None
        self.load()

    # -----------------------------------------------------------------
    def load(self) -> bool:
        """Loads the trained model and its feature importance. Returns True on
        success; on failure the engine stays in physics fallback mode."""
        model_path = self.model_dir / "risk_model.joblib"
        importance_path = self.model_dir / "feature_importance.csv"
        metrics_path = self.model_dir / "model_metrics.json"

        if not model_path.exists() or not importance_path.exists():
            self.load_error = f"Model artefacts not found in {self.model_dir}"
            return False

        try:
            import joblib

            self.model = joblib.load(model_path)
            importance = pd.read_csv(importance_path, index_col=0)
            self.feature_importance = importance.iloc[:, 0]
            self.model_name = type(self.model).__name__
            self.source = "trained_model"
            if metrics_path.exists():
                with open(metrics_path, "r", encoding="utf-8") as handle:
                    self.metrics = json.load(handle)
            self.load_error = None
            return True
        except Exception as exc:                      # noqa: BLE001
            self.model = None
            self.source = "physics_fallback"
            self.load_error = f"{type(exc).__name__}: {exc}"
            return False

    def info(self) -> dict:
        return {
            "source": self.source,
            "model_name": self.model_name,
            "model_dir": str(self.model_dir),
            "features": OBSERVABLE_FEATURES,
            "load_error": self.load_error,
            "metrics": self.metrics,
        }

    # -----------------------------------------------------------------
    def _observation_row(self, zone) -> pd.Series:
        return pd.Series({
            "slope_deg": zone.slope_deg,
            "rainfall_24h_mm": zone.rainfall_24h_mm,
            "rainfall_72h_mm": zone.rainfall_72h_mm,
            "rainfall_7d_mm": zone.rainfall_7d_mm,
            "antecedent_precip_index": zone.antecedent_precip_index,
        })

    def assess(self, zone, sensor_confidence: Optional[dict] = None,
               assessed_at: Optional[str] = None) -> dict:
        observation = self._observation_row(zone)

        if self.model is not None and self.feature_importance is not None:
            prediction = risk_output_schema(self.model, self.feature_importance, observation)
        else:
            score = round(_score_from_fs(zone.factor_of_safety), 1)
            prediction = {
                "risk_score": score,
                "risk_level": _level_from_score(score),
                "probability": round(score / 100.0, 4),
                "contributing_factors": {},
            }

        physics_level = risk_level_from_fs(zone.factor_of_safety)
        alert_level = max(prediction["risk_level"], physics_level, key=lambda lvl: RISK_ORDER[lvl])
        confidence = sensor_confidence or {}

        return {
            "zone_id": zone.zone_id,
            "zone_name": zone.name,
            "state": zone.state,
            "district": zone.district,
            "latitude": zone.latitude,
            "longitude": zone.longitude,
            "assessed_at": assessed_at or None,
            "risk_score": prediction["risk_score"],
            "risk_level": prediction["risk_level"],
            "probability": prediction["probability"],
            "contributing_factors": prediction["contributing_factors"],
            "alert_level": alert_level,
            "physics": {
                "factor_of_safety": round(zone.factor_of_safety, 3),
                "risk_level": physics_level,
                "saturation_ratio": round(zone.saturation_ratio, 4),
                "pore_pressure_kpa": round(zone.pore_pressure_kpa, 2),
                "creep_rate_mm_hr": round(zone.creep_rate_mm_hr, 5),
                "cumulative_displacement_mm": round(zone.cumulative_displacement_mm, 3),
            },
            "observations": {
                "slope_deg": zone.slope_deg,
                "rainfall_24h_mm": round(zone.rainfall_24h_mm, 2),
                "rainfall_72h_mm": round(zone.rainfall_72h_mm, 2),
                "rainfall_7d_mm": round(zone.rainfall_7d_mm, 2),
                "antecedent_precip_index": round(zone.antecedent_precip_index, 2),
                "soil_moisture_pct": round(zone.soil_moisture_pct, 2),
                "rain_rate_mm_hr": round(zone.rain_rate_mm_hr, 2),
            },
            "sensor_confidence": confidence,
            "model": {"source": self.source, "name": self.model_name},
        }

    @staticmethod
    def is_escalation(previous: Optional[str], current: str) -> bool:
        """True when the alert level has risen, which is the trigger condition
        for publishing a zone_alert event."""
        if previous is None:
            return RISK_ORDER[current] >= RISK_ORDER["High"]
        return RISK_ORDER[current] > RISK_ORDER[previous]
