"""Trained-model inference.

The platform was built to prefer the classifier over the rule engine: `RiskZone`
carries a `source` column, `services.rescore_zone` skips a zone whose source is
`ML_MODEL`, and `/api/model/predict` accepts published predictions. But nothing
ever published any. The model sat in `data/ml/risk_model.joblib` and the console
scored every zone with the fallback rules while reporting that the model won —
which was a lie the architecture told about itself.

This module closes that gap by running inference in-process, on the same schedule
as the risk cycle.

Design notes:

1. **The scoring contract is imported, not reimplemented.** `risk_output_schema()`
   lives in `ml/pipeline/train_risk_model.py` and is the same function the training
   script uses. Copying its twelve lines here would have been easier and would have
   drifted the first time somebody re-banded the risk levels. If the two paths ever
   disagree, it should be because someone changed the shared function, not because
   two copies aged differently.

2. **Every dependency is optional.** scikit-learn, joblib and pandas are not in the
   backend's requirements. If they are absent, or the model file is missing, or the
   artefact fails to load, `available()` reports False and the rule engine scores
   everything exactly as before. A district office that cannot install a 90 MB
   scientific stack still gets a working early-warning console; it just gets the
   physics rather than the statistics.

3. **The model does not silently override a worse-case rule score.** The rule
   engine encodes failure physics that the classifier — trained on five observable
   features from a simulated distribution — cannot see: slope movement measured by a
   tiltmeter, a verified road blockage, soil at saturation. Where the rules are more
   alarmed than the model, the rules win. Taking the more severe of two independent
   assessments is the correct bias for early warning, and it is what the streaming
   service does too. A disagreement between the statistical and the mechanical view
   is a reason to warn, not a reason to average.
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import RiskZone

log = logging.getLogger("ner.ml")

# Feature order the model was fitted on. Imported below where possible; this is the
# fallback used only to report what is expected when the pipeline is unavailable.
FEATURES = ["slope_deg", "rainfall_24h_mm", "rainfall_72h_mm",
            "rainfall_7d_mm", "antecedent_precip_index"]

_LEVELS = {"CRITICAL": 3, "HIGH": 2, "MODERATE": 1, "LOW": 0}


@lru_cache(maxsize=1)
def _load() -> dict:
    """Load the model, its feature importances and the shared scoring function.

    Cached: joblib deserialisation of a random forest is not something to do on
    every risk cycle, let alone every zone.
    """
    out: dict = {"model": None, "importance": None, "schema": None,
                 "features": FEATURES, "error": None, "version": None,
                 "warning": None, "sklearn_version": None}

    model_path = Path(settings.ml_data_dir) / "risk_model.joblib"
    if not model_path.is_file():
        out["error"] = f"No model artefact at {model_path}"
        return out

    try:
        import joblib
        import pandas as pd
    except ImportError as exc:
        out["error"] = (f"Inference dependencies not installed ({exc.name}). "
                        "Install backend extras: pip install -r requirements-ml.txt")
        return out

    # Make ml/ importable so the online path can share the offline scoring contract.
    ml_root = Path(settings.repo_root) / "ml"
    if ml_root.is_dir() and str(ml_root) not in sys.path:
        sys.path.insert(0, str(ml_root))

    try:
        from pipeline.train_risk_model import OBSERVABLE_FEATURES, risk_output_schema
        out["features"] = list(OBSERVABLE_FEATURES)
        out["schema"] = risk_output_schema
    except Exception as exc:  # noqa: BLE001
        # Not fatal: we can still score, we just cannot share the contract. Say so
        # loudly, because this is exactly the drift the shared import prevents.
        log.warning("shared scoring contract unavailable (%s); using local banding", exc)

    try:
        import warnings

        import sklearn
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out["model"] = joblib.load(model_path)
        # A pickle written by a different scikit-learn can load and then behave
        # subtly differently. sklearn only warns, and a warning in a server log is
        # a warning nobody reads, so it is promoted onto the model status panel.
        mismatch = next((str(w.message) for w in caught
                         if "InconsistentVersionWarning" in type(w.message).__name__), None)
        out["sklearn_version"] = sklearn.__version__
        if mismatch:
            out["warning"] = (
                f"Model was pickled under a different scikit-learn than the one "
                f"loading it (running {sklearn.__version__}). Predictions are usable "
                f"but should be re-verified; retrain with "
                f"`python ml/pipeline/train_risk_model.py` to clear this."
            )
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"Model artefact could not be loaded: {exc}"
        return out

    importance_path = Path(settings.ml_data_dir) / "feature_importance.csv"
    if importance_path.is_file():
        try:
            frame = pd.read_csv(importance_path, header=None, names=["feature", "importance"])
            frame = frame[frame["feature"].isin(out["features"])]
            out["importance"] = frame.set_index("feature")["importance"].astype(float)
        except Exception:  # noqa: BLE001
            out["importance"] = None

    out["version"] = f"{type(out['model']).__name__.lower()}-{model_path.stat().st_size}"
    return out


def available() -> bool:
    return _load()["model"] is not None


def status() -> dict:
    """What the console reports on the model panel."""
    state = _load()
    return {
        "available": state["model"] is not None,
        "algorithm": type(state["model"]).__name__ if state["model"] else None,
        "model_version": state["version"],
        "features": state["features"],
        "shares_training_contract": state["schema"] is not None,
        "model_path": str(Path(settings.ml_data_dir) / "risk_model.joblib"),
        "error": state["error"],
        "warning": state.get("warning"),
        "sklearn_version": state.get("sklearn_version"),
        "note": (
            "Inference runs in-process on each risk cycle. Where the rule engine is "
            "more alarmed than the model, the rule engine's score is kept."
        ),
    }


def _band(score: float) -> str:
    b = settings.bands
    if score >= b.critical:
        return "CRITICAL"
    if score >= b.high:
        return "HIGH"
    if score >= b.moderate:
        return "MODERATE"
    return "LOW"


def score_zones(db: Session, zones: list[RiskZone] | None = None) -> dict:
    """Score every zone with the classifier and record the result.

    Returns a summary rather than raising when the model is unavailable: this is
    called from inside the risk cycle, and a missing scientific stack must degrade
    the platform to rule-based scoring, not stop the cycle.
    """
    state = _load()
    model = state["model"]
    if model is None:
        return {"scored": 0, "available": False, "reason": state["error"]}

    import pandas as pd

    if zones is None:
        zones = db.query(RiskZone).all()

    # A zone whose score was deliberately published by an external pipeline is left
    # alone until that publish expires. In-process inference is a fallback for the
    # common case where nothing external is publishing at all — it must not race a
    # pipeline that is.
    from ..services import published_recently
    zones = [z for z in zones if not published_recently(z)]

    if not zones:
        return {"scored": 0, "available": True, "applied": 0}

    features = state["features"]
    frame = pd.DataFrame(
        [[
            zone.slope_deg,
            zone.rainfall_24h_mm,
            zone.rainfall_72h_mm,
            zone.rainfall_7d_mm,
            zone.antecedent_precip_index,
        ] for zone in zones],
        columns=FEATURES,
    )[features]

    try:
        probabilities = model.predict_proba(frame)[:, 1]
    except Exception as exc:  # noqa: BLE001
        log.exception("inference failed")
        return {"scored": 0, "available": False, "reason": f"Inference failed: {exc}"}

    applied = kept = 0
    importance = state["importance"]
    schema = state["schema"]

    for zone, probability in zip(zones, probabilities):
        model_score = round(float(probability) * 100, 1)

        # Contributing factors from the shared function where it is importable, so
        # the explanation an operator reads matches the one the training script
        # produces for the same row.
        factors = None
        if schema is not None and importance is not None:
            try:
                row = frame.loc[frame.index[zones.index(zone)]]
                factors = schema(model, importance, row).get("contributing_factors")
            except Exception:  # noqa: BLE001
                factors = None

        # The rule engine sees evidence the classifier's five features cannot:
        # measured movement, verified blockages, saturation. Keep the worse case.
        if model_score <= zone.risk_score:
            kept += 1
            zone.model_probability = float(probability)
            continue

        zone.risk_score = model_score
        zone.risk_level = _band(model_score)
        zone.probability = float(probability)
        zone.model_probability = float(probability)
        zone.source = "ML_MODEL"
        zone.model_version = state["version"]
        if factors:
            zone.contributing_factors = factors
        applied += 1

    db.flush()
    return {
        "scored": len(zones),
        "available": True,
        "applied": applied,
        "rule_engine_kept": kept,
        "model_version": state["version"],
    }
