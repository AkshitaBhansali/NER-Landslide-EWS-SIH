"""/api — weather, system, notifications, reference data, thresholds."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..config import settings
from ..core.notify import LANGUAGE_NAMES, TIER_AUDIENCES, TIER_STATUS
from ..data.regions import DISTRICTS, STATES
from ..deps import Session, get_case, get_db, require_role, respond
from ..models import District, Notification, Recipient, WeatherObservation

router = APIRouter(prefix="/api", tags=["platform"])


@router.get("/districts")
def districts(response: Response, case: str | None = Depends(get_case)):
    return respond({"states": STATES, "districts": DISTRICTS}, case, response)


@router.get("/weather")
def weather(
    response: Response,
    district: str | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = select(WeatherObservation).order_by(WeatherObservation.observed_at.desc())
    if district and district != "ALL":
        row = db.scalars(q.where(WeatherObservation.district_id == district)).first()
        if not row:
            raise HTTPException(404, f"No weather for {district}")
        return respond(S.weather(row), case, response)

    # No district selected: return the district closest to breaching its threshold,
    # because on a regional dashboard that is the only one anybody needs to see.
    rows = db.scalars(q).all()
    latest: dict[str, WeatherObservation] = {}
    for r in rows:
        latest.setdefault(r.district_id, r)
    if not latest:
        raise HTTPException(404, "No weather observations")
    worst = max(latest.values(), key=lambda w: w.rainfall_24h_mm / max(w.alert_threshold_24h, 1))
    return respond(S.weather(worst), case, response)


@router.get("/weather/all")
def weather_all(response: Response, db: Session = Depends(get_db),
                case: str | None = Depends(get_case)):
    rows = db.scalars(
        select(WeatherObservation).order_by(WeatherObservation.observed_at.desc())
    ).all()
    latest: dict[str, WeatherObservation] = {}
    for r in rows:
        latest.setdefault(r.district_id, r)
    return respond([S.weather(w) for w in latest.values()], case, response)


@router.get("/system/status")
def system_status(response: Response, db: Session = Depends(get_db),
                  case: str | None = Depends(get_case)):
    return respond(services.system_status(db), case, response)


@router.get("/notifications")
def notifications(response: Response, db: Session = Depends(get_db),
                  case: str | None = Depends(get_case)):
    rows = db.scalars(select(Notification).order_by(Notification.created_at.desc())).all()
    return respond([S.notification(n) for n in rows], case, response)


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: str, response: Response, db: Session = Depends(get_db),
              case: str | None = Depends(get_case)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    n.read = True
    db.commit()
    return respond(S.notification(n), case, response)


@router.post("/notifications/read-all")
def mark_all_read(response: Response, db: Session = Depends(get_db),
                  case: str | None = Depends(get_case)):
    for n in db.scalars(select(Notification).where(Notification.read.is_(False))).all():
        n.read = True
    db.commit()
    return respond({"ok": True}, case, response)


# --------------------------------------------------------------------------- #
# Settings — backs the /settings page.
# --------------------------------------------------------------------------- #
@router.get("/settings/thresholds")
def get_thresholds(response: Response, db: Session = Depends(get_db),
                   case: str | None = Depends(get_case)):
    per_district = [
        {"district_id": d.id, "district": d.name, "alert_threshold_24h": d.alert_threshold_24h}
        for d in db.scalars(select(District).order_by(District.name)).all()
    ]
    return respond({
        "risk_bands": {"critical": settings.bands.critical, "high": settings.bands.high,
                       "moderate": settings.bands.moderate},
        "alert_tiers": {"red": settings.tiers.red, "orange": settings.tiers.orange,
                        "yellow": settings.tiers.yellow},
        "tier_audiences": TIER_AUDIENCES,
        "tier_status": TIER_STATUS,
        "dispatch_cutoff": settings.dispatch_cutoff,
        "cooldown_minutes": settings.alert_cooldown_minutes,
        "rainfall_t_crit": {"h24": settings.t_crit_24h, "h72": settings.t_crit_72h,
                            "d7": settings.t_crit_7d},
        "weights": {"static_lsi": settings.w_static, "dynamic_ti": settings.w_dynamic},
        "district_thresholds": per_district,
        "note": ("Risk bands drive what the console shows. Alert tiers drive who receives "
                 "an SMS. They are separate on purpose \u2014 changing who gets woken up "
                 "should not repaint the map."),
    }, case, response)


@router.patch("/settings/thresholds/{district_id}")
def set_district_threshold(
    district_id: str,
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("STATE_ADMIN")),
    case: str | None = Depends(get_case),
):
    d = db.get(District, district_id)
    if not d:
        raise HTTPException(404, f"District {district_id} not found")
    value = body.get("alert_threshold_24h")
    if value is None or not (10 <= float(value) <= 500):
        raise HTTPException(400, "alert_threshold_24h must be between 10 and 500 mm")
    d.alert_threshold_24h = float(value)
    db.commit()
    return respond({"district_id": d.id, "alert_threshold_24h": d.alert_threshold_24h},
                   case, response)


@router.get("/settings/languages")
def languages(response: Response, case: str | None = Depends(get_case)):
    from ..core.notify import TEMPLATES

    return respond([
        {"code": code, "name": name,
         "templates": sorted(TEMPLATES.get(code, {}).keys()),
         "complete": set(TEMPLATES.get(code, {}).keys()) >= {"AUTHORITY", "LOCAL", "PUBLIC"}}
        for code, name in LANGUAGE_NAMES.items()
    ], case, response)


@router.get("/recipients")
def recipients(
    response: Response,
    district: str | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = select(Recipient)
    if district and district != "ALL":
        q = q.where(Recipient.district_id == district)
    return respond([S.recipient(r) for r in db.scalars(q).all()], case, response)
