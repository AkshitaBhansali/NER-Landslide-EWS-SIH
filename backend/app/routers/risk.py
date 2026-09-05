"""/api/risk — zones, summary, trend, explainability."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..core.risk_engine import RiskResult, explain
from ..deps import Scope, Session, get_case, get_db, get_scope, respond
from ..models import RiskZone

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/zones")
def list_zones(
    response: Response,
    scope: Scope = Depends(get_scope),
    level: str | None = Query(None, description="Filter by risk level"),
    min_score: float | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = services.apply_scope(select(RiskZone), RiskZone, scope.state_code, scope.district_id)
    if level:
        q = q.where(RiskZone.risk_level == level.upper())
    if min_score is not None:
        q = q.where(RiskZone.risk_score >= min_score)
    zones = db.scalars(q.order_by(RiskZone.risk_score.desc())).all()
    return respond([S.risk_zone(z) for z in zones], case, response)


@router.get("/summary")
def summary(
    response: Response,
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    return respond(services.risk_summary(db, scope.state_code, scope.district_id), case, response)


@router.get("/pipeline")
def pipeline(
    response: Response,
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Feeds the pipeline strip on the overview page."""
    return respond(services.pipeline_status(db, scope.state_code, scope.district_id), case, response)


@router.get("/trend")
def trend(
    response: Response,
    district: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    return respond(services.risk_trend(db, district, days), case, response)


@router.get("/zones/{zone_id}")
def get_zone(
    zone_id: str,
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    z = db.get(RiskZone, zone_id)
    if not z:
        raise HTTPException(404, f"Zone {zone_id} not found")
    return respond(S.risk_zone(z), case, response)


@router.get("/zones/{zone_id}/explain")
def explain_zone(
    zone_id: str,
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Why this zone scores what it scores.

    Exposed as a first-class endpoint because an early-warning system that cannot
    justify a warning will not get one acted on. A DM who is being asked to close a
    highway is entitled to see which factor drove the number.
    """
    z = db.get(RiskZone, zone_id)
    if not z:
        raise HTTPException(404, f"Zone {zone_id} not found")
    fake = RiskResult(
        lsi=z.lsi, ti=z.ti, risk_score=z.risk_score, risk_level=z.risk_level,
        alert_tier=z.alert_tier, probability=z.probability,
        contributing_factors=z.contributing_factors, components={},
    )
    payload = {
        "zone_id": z.id,
        "risk_score": z.risk_score,
        "risk_level": z.risk_level,
        "alert_tier": z.alert_tier,
        "probability": z.probability,
        "source": z.source,
        "model_version": z.model_version,
        "sensor_confidence": z.sensor_confidence,
        "inputs": {
            "slope_deg": z.slope_deg, "soil_type": z.soil_type,
            "landcover": z.landcover, "elevation_m": z.elevation_m,
            "aspect_deg": z.aspect_deg, "rainfall_24h_mm": z.rainfall_24h_mm,
            "rainfall_72h_mm": z.rainfall_72h_mm, "rainfall_7d_mm": z.rainfall_7d_mm,
            "soil_moisture_pct": z.soil_moisture_pct,
            "antecedent_precip_index": z.antecedent_precip_index,
        },
        **explain(fake),
    }
    return respond(payload, case, response)
