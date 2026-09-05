"""
ML Risk Classification Pipeline
===============================

Purpose
-------
Trains and compares Random Forest and XGBoost classifiers for landslide risk
classification, and produces the platform output contract: risk_score,
risk_level, probability and contributing_factors.

Feature selection
-----------------
Training uses observable features only, meaning quantities a deployed system
can measure from a sensor network, a DEM and a rainfall gauge:

    slope_deg, rainfall_24h_mm, rainfall_72h_mm, rainfall_7d_mm,
    antecedent_precip_index

Physics internals from physics_slope_model.py (factor_of_safety,
saturation_ratio, pore_pressure_kpa and the contribution columns) are excluded
as inputs, because they are the internal state of the label generator and
using them would leak the target, producing accuracy figures that do not
survive deployment. Depth to slip surface, cohesion and friction angle are
also excluded, because a deployed system obtains them from a one-time
geotechnical survey per site rather than a live sensor feed; they are used
only to generate physically consistent labels.

The feature set matches HISTORICAL_EVENT_SCHEMA, so the trained model can be
pointed at real historical and live sensor data without feature
re-engineering.
"""

from __future__ import annotations
import json
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (roc_auc_score, accuracy_score, precision_score,
                              recall_score, f1_score, confusion_matrix)

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulation"))
from physics_slope_model import risk_level_from_fs  # noqa: E402


# Features an actual deployed system can observe live: rainfall gauges,
# DEM-derived slope, and antecedent-rainfall memory. This is intentionally
# the same feature family as HISTORICAL_EVENT_SCHEMA (rainfall_24h/
# 72h/7d, antecedent_precip_index, slope_deg) so the same trained model can
# later be pointed at real historical + live sensor data without a feature
# re-engineering pass.
def _xgb_classifier():
    """Import XGBoost only when a model is actually being trained.

    XGBoost is a training-time dependency. It was imported at module scope, which
    meant anything wanting `risk_output_schema()` for *inference* — the live
    streaming service and the platform backend both do — had to install a gradient
    boosting library to score a slope. Deferring the import lets the online and
    offline paths keep sharing this one function, which is the whole reason they
    cannot drift apart.
    """
    from xgboost import XGBClassifier
    return XGBClassifier


OBSERVABLE_FEATURES = [
    "slope_deg",
    "rainfall_24h_mm",
    "rainfall_72h_mm",
    "rainfall_7d_mm",
    "antecedent_precip_index",
]
TARGET = "landslide_occurred"


def load_dataset(path: str = "../data/synthetic_slope_scenarios.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    if "risk_level" not in df.columns:
        df["risk_level"] = df["factor_of_safety"].apply(risk_level_from_fs)
    return df


def train_models(df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42):
    X = df[OBSERVABLE_FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y)

    models = {
        "random_forest": RandomForestClassifier(
            n_estimators=300, max_depth=10, min_samples_leaf=5,
            class_weight="balanced", random_state=random_state, n_jobs=-1),
        "xgboost": _xgb_classifier()(
            n_estimators=400, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
            random_state=random_state, n_jobs=-1),
    }

    results = {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]
        pred = model.predict(X_test)

        metrics = {
            "roc_auc": round(roc_auc_score(y_test, proba), 4),
            "accuracy": round(accuracy_score(y_test, pred), 4),
            "precision": round(precision_score(y_test, pred), 4),
            "recall": round(recall_score(y_test, pred), 4),
            "f1": round(f1_score(y_test, pred), 4),
            "confusion_matrix": confusion_matrix(y_test, pred).tolist(),
        }
        results[name] = {"model": model, "metrics": metrics}
        print(f"\n{name.upper()}")
        for k, v in metrics.items():
            if k != "confusion_matrix":
                print(f"  {k:10s}: {v}")
        print(f"  confusion_matrix (rows=actual, cols=pred): {metrics['confusion_matrix']}")

    best_name = max(results, key=lambda k: results[k]["metrics"]["roc_auc"])
    print(f"\nBest model by ROC-AUC: {best_name}")

    feat_imp = pd.Series(
        results[best_name]["model"].feature_importances_, index=OBSERVABLE_FEATURES
    ).sort_values(ascending=False)
    print(f"\nFeature importance ({best_name}):\n{feat_imp}")

    return results, best_name, feat_imp, (X_test, y_test)


def risk_output_schema(model, feat_imp: pd.Series, row: pd.Series) -> dict:
    """
    Produces the platform output contract: risk_score, risk_level,
    probability and contributing_factors. The backend
    `prediction_generation_service.py` equivalent for this project calls it
    per sensor cluster or grid cell, and the dashboard renders its output
    directly.
    """
    X = row[OBSERVABLE_FEATURES].to_frame().T
    probability = float(model.predict_proba(X)[0, 1])
    risk_score = round(probability * 100, 1)

    if risk_score >= 70:
        risk_level = "Critical"
    elif risk_score >= 45:
        risk_level = "High"
    elif risk_score >= 20:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    # Per-row contributing factors: feature value weighted by global importance,
    # normalized to sum to 1 - cheap, model-agnostic, good enough for an alert
    # panel ("rainfall accumulation is driving this alert"); swap for SHAP once
    # inference latency budget allows it.
    weighted = (row[OBSERVABLE_FEATURES] / row[OBSERVABLE_FEATURES].abs().sum()).abs() * feat_imp
    weighted = (weighted / weighted.sum()).sort_values(ascending=False)

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "probability": round(probability, 4),
        "contributing_factors": {k: round(float(v), 3) for k, v in weighted.items()},
    }


def save_artifacts(results: dict, best_name: str, feat_imp: pd.Series, out_dir: str = "../data"):
    os.makedirs(out_dir, exist_ok=True)
    joblib.dump(results[best_name]["model"], os.path.join(out_dir, "risk_model.joblib"))
    with open(os.path.join(out_dir, "model_metrics.json"), "w") as f:
        json.dump({k: v["metrics"] for k, v in results.items()}, f, indent=2)
    feat_imp.to_csv(os.path.join(out_dir, "feature_importance.csv"), header=["importance"])
    print(f"\nSaved: {out_dir}/risk_model.joblib, model_metrics.json, feature_importance.csv")


if __name__ == "__main__":
    df = load_dataset()
    results, best_name, feat_imp, (X_test, y_test) = train_models(df)
    save_artifacts(results, best_name, feat_imp)

    print("\n--- Example risk_output_schema for 3 test rows ---")
    best_model = results[best_name]["model"]
    sample = X_test.join(y_test).sample(3, random_state=1)
    for _, row in sample.iterrows():
        out = risk_output_schema(best_model, feat_imp, row)
        print(f"\n(actual landslide_occurred={int(row[TARGET])})")
        print(json.dumps(out, indent=2))
