"""/api/sensors — fleet state, readings, health."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..core.sensor_health import WEIGHTS
from ..deps import Scope, Session, get_case, get_db, get_scope, respond
from ..models import Sensor, SensorReading, utcnow

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


@router.get("")
def list_sensors(
    response: Response,
    scope: Scope = Depends(get_scope),
    status: str | None = Query(None),
    sensor_type: str | None = Query(None),
    zone_id: str | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = services.apply_scope(select(Sensor), Sensor, scope.state_code, scope.district_id)
    if status:
        q = q.where(Sensor.status == status.upper())
    if sensor_type:
        q = q.where(Sensor.sensor_type == sensor_type.upper())
    if zone_id:
        q = q.where(Sensor.zone_id == zone_id)
    rows = db.scalars(q.order_by(Sensor.health_score.asc())).all()
    return respond([S.sensor(s) for s in rows], case, response)


@router.get("/summary")
def summary(
    response: Response,
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    payload = services.sensor_fleet_summary(db, scope.state_code, scope.district_id)
    payload["health_weights"] = WEIGHTS
    return respond(payload, case, response)


@router.get("/{sensor_id}")
def get_sensor(sensor_id: str, response: Response, db: Session = Depends(get_db),
               case: str | None = Depends(get_case)):
    s = db.get(Sensor, sensor_id)
    if not s:
        raise HTTPException(404, f"Sensor {sensor_id} not found")
    return respond(S.sensor(s), case, response)


@router.get("/{sensor_id}/readings")
def readings(
    sensor_id: str,
    response: Response,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    if not db.get(Sensor, sensor_id):
        raise HTTPException(404, f"Sensor {sensor_id} not found")
    since = utcnow() - timedelta(hours=hours)
    rows = db.scalars(
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor_id, SensorReading.timestamp >= since)
        .order_by(SensorReading.timestamp)
    ).all()
    return respond([S.sensor_reading(r) for r in rows], case, response)
