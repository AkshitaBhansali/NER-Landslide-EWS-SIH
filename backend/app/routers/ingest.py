"""/api/ingest — the inbound edge of the platform.

This is where the model, the data pipeline and the IMD feed connect. Each
endpoint validates, records provenance, and then triggers whatever downstream work
the new data justifies.

Provenance is the part that is easy to skip and expensive to retrofit. Every score
carries `source` and `model_version`, so six weeks from now, when a warning is
questioned, we can say exactly which model produced it and on what inputs — instead
of guessing.
"""
from __future__ import annotations

from datetime import datetime

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import services
from ..config import settings
from ..core.risk_engine import (
    RECOMMENDED_ACTION,
    alert_tier_from_score,
    expected_window_hours,
    risk_level_from_score,
)
from ..data.regions import DISTRICT_BY_ID
from ..deps import Session, get_case, get_db, require_role, respond
from ..models import ModelRun, RiskZone, Sensor, SensorReading, WeatherObservation, utcnow

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest/readings", status_code=202)
def ingest_readings(
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Batch sensor readings from a gateway.

    Accepts duplicates silently. A LoRa gateway doing store-and-forward WILL resend
    what it already sent — the unique constraint on (sensor_id, timestamp) makes
    that harmless, so the gateway can be dumb and retry blindly.
    """
    rows = body.get("readings") or []
    accepted = duplicates = rejected = 0
    errors: list[str] = []

    for r in rows:
        sid = r.get("sensor_id")
        sensor = db.get(Sensor, sid)
        if not sensor:
            rejected += 1
            errors.append(f"Unknown sensor {sid}")
            continue
        try:
            ts = datetime.fromisoformat(r["timestamp"])
            value = float(r["value"])
        except (KeyError, ValueError, TypeError) as exc:
            rejected += 1
            errors.append(f"{sid}: {exc}")
            continue

        reading = SensorReading(
            sensor_id=sid, timestamp=ts, value=value,
            unit=r.get("unit", sensor.unit),
            quality_flag=r.get("quality_flag", "OK"),
        )
        db.add(reading)
        try:
            db.flush()
            accepted += 1
            if ts > (sensor.last_seen.replace(tzinfo=ts.tzinfo) if sensor.last_seen else ts):
                sensor.last_seen = ts
                sensor.reading = value
            if r.get("battery_pct") is not None:
                sensor.battery_pct = float(r["battery_pct"])
            if r.get("rssi_dbm") is not None:
                sensor.rssi_dbm = float(r["rssi_dbm"])
        except IntegrityError:
            db.rollback()
            duplicates += 1

    db.commit()
    return respond({
        "accepted": accepted, "duplicates": duplicates, "rejected": rejected,
        "errors": errors[:10], "received_at": utcnow().isoformat(),
    }, case, response)


@router.get("/model/status")
def model_status(response: Response, case: str | None = Depends(get_case)):
    """Whether the trained classifier is loaded, and on what.

    Surfaced because "is the model actually running?" was previously unanswerable
    from outside the process — the platform reported ML precedence in its
    architecture while scoring everything with the fallback rules.
    """
    from ..core import ml_model
    return respond(ml_model.status(), case, response)


@router.post("/model/score", status_code=200)
def model_score_now(
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Run inference over every zone immediately."""
    from ..core import ml_model
    return respond(ml_model.score_zones(db), case, response)


@router.post("/model/predict", status_code=202)
def ingest_predictions(
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Publish model output.

    Contract (matches `risk_output_schema()` in the pipeline):

        {
          "model_version": "rf-2026.09.01",
          "algorithm": "RandomForest",
          "metrics": {...}, "feature_importance": [...],
          "predictions": [
            {"zone_id": "as-dima-hasao-z1", "risk_score": 84.2,
             "risk_level": "CRITICAL", "probability": 0.88,
             "contributing_factors": {...}}
          ]
        }

    If the model emits its own `risk_level`, that value wins over the local band
    function — the model may have been calibrated against thresholds we do not
    know about, and silently re-binning its output would misrepresent it.
    """
    version = body.get("model_version") or "unversioned"
    preds = body.get("predictions") or []
    if not preds:
        raise HTTPException(400, "predictions[] is required")

    updated, unknown = 0, []
    for p in preds:
        z = db.get(RiskZone, p.get("zone_id"))
        if not z:
            unknown.append(p.get("zone_id"))
            continue
        score = float(p.get("risk_score", 0))
        z.risk_score = score
        z.risk_level = (p.get("risk_level") or risk_level_from_score(score)).upper()
        z.alert_tier = p.get("alert_tier") or alert_tier_from_score(score)
        z.probability = float(p.get("probability", z.probability))
        if p.get("contributing_factors"):
            z.contributing_factors = p["contributing_factors"]
        z.expected_window_hours = expected_window_hours(z.risk_level)
        z.recommended_action = RECOMMENDED_ACTION.get(z.risk_level, z.recommended_action)
        z.source = "ML_MODEL"
        z.model_published_at = utcnow()
        z.model_version = version
        z.data_confidence = p.get("data_confidence", z.data_confidence)
        updated += 1

    run = ModelRun(
        model_version=version,
        algorithm=body.get("algorithm", "RandomForest"),
        zones_scored=updated,
        metrics=body.get("metrics") or {},
        feature_importance=body.get("feature_importance") or [],
        evaluated_on=body.get("evaluated_on", ""),
        caveat=body.get("caveat", ""),
    )
    db.add(run)
    db.commit()

    # New scores mean the alert picture may have changed. Re-evaluate immediately
    # rather than waiting for the next scheduled tick — a fifteen-minute delay on a
    # critical score is fifteen minutes of a warning that existed but was not sent.
    cycle = services.run_risk_cycle(db, send=True)

    return respond({
        "model_version": version, "zones_updated": updated,
        "unknown_zones": unknown[:20], "cycle": cycle,
    }, case, response)


@router.post("/ingest/weather", status_code=202)
def ingest_weather(
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Push weather observations (IMD or any gridded product)."""
    rows = body.get("observations") or []
    accepted, rejected = 0, []
    for o in rows:
        d = DISTRICT_BY_ID.get(o.get("district_id"))
        if not d:
            rejected.append(o.get("district_id"))
            continue
        db.add(WeatherObservation(
            district_id=d["id"], district=d["name"],
            observed_at=datetime.fromisoformat(o["observed_at"])
            if o.get("observed_at") else utcnow(),
            rainfall_now_mm=float(o.get("rainfall_now_mm", 0)),
            rainfall_24h_mm=float(o.get("rainfall_24h_mm", 0)),
            rainfall_72h_mm=float(o.get("rainfall_72h_mm", 0)),
            rainfall_7d_mm=float(o.get("rainfall_7d_mm", 0)),
            humidity_pct=float(o.get("humidity_pct", 0)),
            temperature_c=float(o.get("temperature_c", 0)),
            wind_kph=float(o.get("wind_kph", 0)),
            condition=o.get("condition", "CLEAR"),
            alert_threshold_24h=float(o.get("alert_threshold_24h", 95)),
            forecast=o.get("forecast") or [],
            source=o.get("source", "IMD"),
        ))
        accepted += 1
    db.commit()
    return respond({"accepted": accepted, "rejected": rejected}, case, response)


@router.post("/ingest/imd/pull", status_code=202)
def pull_imd(
    response: Response,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("STATE_ADMIN")),
    case: str | None = Depends(get_case),
):
    """Pull from the configured IMD endpoint.

    Left as an explicit, configurable call rather than a hard-coded scrape: IMD's
    public surface changes, and a scraper that silently breaks is worse than an
    endpoint that plainly reports it is not configured.
    """
    if not settings.imd_api_base:
        return respond({
            "status": "NOT_CONFIGURED",
            "detail": "Set IMD_API_BASE and IMD_API_KEY. Until then weather is seeded "
                      "and labelled IMD_PLACEHOLDER.",
        }, case, response)
    try:
        r = httpx.get(
            f"{settings.imd_api_base.rstrip('/')}/rainfall",
            headers={"Authorization": f"Bearer {settings.imd_api_key}"},
            timeout=20.0,
        )
        r.raise_for_status()
        return respond({"status": "OK", "records": len(r.json() or [])}, case, response)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"IMD fetch failed: {str(exc)[:180]}") from exc


@router.post("/engine/run", status_code=200)
def run_engine(
    response: Response,
    send: bool = True,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("DDMA")),
    case: str | None = Depends(get_case),
):
    """Trigger a risk cycle by hand. The same code path the
    scheduler calls — so what you show on stage is what runs in production."""
    return respond(services.run_risk_cycle(db, send=send), case, response)
