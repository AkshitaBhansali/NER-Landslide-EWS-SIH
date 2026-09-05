"""/api/alerts — the alert engine's public surface."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..core import alert_engine as ae
from ..core import notify
from ..deps import Scope, Session, get_case, get_db, get_scope, require_role, respond
from ..models import Alert, AlertEvent, Dispatch

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    response: Response,
    scope: Scope = Depends(get_scope),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    trigger: str | None = Query(None),
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = services.apply_scope(select(Alert), Alert, scope.state_code, scope.district_id)
    if severity:
        q = q.where(Alert.severity == severity.upper())
    if status:
        q = q.where(Alert.status == status.upper())
    if trigger:
        q = q.where(Alert.trigger == trigger.upper())
    if active_only:
        q = q.where(Alert.status != "RESOLVED")
    rows = db.scalars(q.order_by(Alert.risk_score.desc(), Alert.issued_at.desc())).all()
    return respond([S.alert(a) for a in rows], case, response)


@router.get("/{alert_id}")
def get_alert(alert_id: str, response: Response, db: Session = Depends(get_db),
              case: str | None = Depends(get_case)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alert {alert_id} not found")
    return respond(S.alert(a), case, response)


@router.get("/{alert_id}/timeline")
def alert_timeline(alert_id: str, response: Response, db: Session = Depends(get_db),
                   case: str | None = Depends(get_case)):
    """Full audit trail. Who knew what, when, and what was sent to whom.

    This is the artefact that matters after an event, when the question stops being
    'did the model work' and becomes 'was the warning issued, and did it arrive'.
    """
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alert {alert_id} not found")
    events = db.scalars(
        select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.at)
    ).all()
    dispatches = db.scalars(select(Dispatch).where(Dispatch.alert_id == alert_id)).all()
    return respond({
        "alert": S.alert(a),
        "events": [S.alert_event(e) for e in events],
        "dispatches": [S.dispatch(d) for d in dispatches],
        "delivery": notify.delivery_summary(db, alert_id),
    }, case, response)


@router.post("/{alert_id}/acknowledge")
def acknowledge(
    alert_id: str,
    response: Response,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("DDMA")),
    case: str | None = Depends(get_case),
):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alert {alert_id} not found")
    actor = body.get("actor") or f"DDMA {a.district}"
    try:
        ae.transition(db, a, "ACKNOWLEDGED", actor, body.get("note", ""))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return respond(S.alert(a), case, response)


@router.post("/{alert_id}/dispatch")
def dispatch_response(
    alert_id: str,
    response: Response,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("DDMA")),
    case: str | None = Depends(get_case),
):
    """Move to IN_PROGRESS and push the warning out again to the tier audience."""
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alert {alert_id} not found")
    actor = body.get("actor") or f"DDMA {a.district}"
    if a.status == "NEW":
        ae.transition(db, a, "ACKNOWLEDGED", actor, "auto-acknowledged on dispatch")
    try:
        ae.transition(db, a, "IN_PROGRESS", actor, body.get("note", ""))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    notify.queue_for_alert(db, a)
    db.flush()
    result = notify.flush_queue(db)
    db.commit()
    payload = S.alert(a)
    payload["delivery"] = result
    return respond(payload, case, response)


@router.post("/{alert_id}/resolve")
def resolve(
    alert_id: str,
    response: Response,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("DDMA")),
    case: str | None = Depends(get_case),
):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alert {alert_id} not found")
    try:
        ae.transition(db, a, "RESOLVED", body.get("actor") or "DDMA", body.get("note", ""))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return respond(S.alert(a), case, response)


@router.get("/delivery/summary")
def delivery(response: Response, db: Session = Depends(get_db),
             case: str | None = Depends(get_case)):
    return respond(notify.delivery_summary(db), case, response)


@router.post("/delivery/retry")
def retry_delivery(
    response: Response,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("DDMA")),
    case: str | None = Depends(get_case),
):
    """Drain the store-and-forward queue. Called by the worker, or by hand when a
    district office gets its link back."""
    result = notify.flush_queue(db)
    db.commit()
    return respond(result, case, response)
