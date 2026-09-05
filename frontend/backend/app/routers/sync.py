"""/api/sync — offline-first support.

The deployment reality this exists for: a field officer in Dima Hasao during a
monsoon has no usable data link for hours at a time, and that is exactly when the
platform matters most. So the design assumption is inverted — the network is
assumed absent and treated as an occasional bonus, rather than assumed present and
patched when it fails.

Three pieces:

  GET  /api/sync/bundle   A district snapshot small enough to cache in IndexedDB.
                          Everything the app needs to be USEFUL with no network:
                          zones, roads, villages, open alerts, thresholds, contacts.

  POST /api/sync/batch    Idempotent replay of queued client operations. Every
                          operation carries a client_id; replaying an already-
                          accepted client_id returns the original server record
                          instead of creating a duplicate. This is non-negotiable:
                          a flaky uplink retries, and five copies of one landslide
                          report is worse than none, because it fakes corroboration.

  GET  /api/sync/delta    Changed-since feed so a reconnecting device pulls a few
                          kilobytes instead of the whole bundle.

Conflict policy: server wins for authority-owned state (alert status, verification),
client wins for field-captured state (report content, GPS, timestamps). The device
observed the ground; the server did not.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..config import settings
from ..deps import Scope, Session, get_case, get_db, get_scope, respond
from ..models import (
    Alert,
    District,
    IncidentReport,
    Recipient,
    RiskZone,
    Road,
    SyncLedger,
    Village,
    utcnow,
)
from .incidents import _persist_report

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/bundle")
def bundle(
    response: Response,
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    st, di = scope.state_code, scope.district_id
    zones = db.scalars(services.apply_scope(select(RiskZone), RiskZone, st, di)).all()
    roads = db.scalars(services.apply_scope(select(Road), Road, st, di)).all()
    villages = db.scalars(services.apply_scope(select(Village), Village, st, di)).all()
    alerts = [a for a in db.scalars(services.apply_scope(select(Alert), Alert, st, di)).all()
              if a.status != "RESOLVED"]
    districts = db.scalars(select(District)).all()
    if di and di != "ALL":
        districts = [d for d in districts if d.id == di]

    payload = {
        "generated_at": utcnow().isoformat(),
        "scope": {"state_code": st, "district_id": di},
        "zones": [S.risk_zone(z) for z in zones],
        "roads": [S.road(r) for r in roads],
        "villages": [S.village(v) for v in villages],
        "active_alerts": [S.alert(a) for a in alerts],
        "thresholds": [
            {"district_id": d.id, "district": d.name,
             "alert_threshold_24h": d.alert_threshold_24h} for d in districts
        ],
        # Contact list so a field officer can still escalate by voice when the data
        # link is gone but the voice network is up. They frequently are not the same.
        "escalation_contacts": [
            S.recipient(r) for r in db.scalars(
                select(Recipient).where(Recipient.audience == "AUTHORITY")
            ).all() if not di or di == "ALL" or r.district_id == di
        ],
        "data_confidence": settings.data_confidence,
    }
    # ETag lets a reconnecting device skip the download entirely when nothing moved.
    etag = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    payload["etag"] = etag
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=300"
    return respond(payload, case, response)


@router.get("/delta")
def delta(
    response: Response,
    since: str = Query(..., description="ISO timestamp of the client's last sync"),
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    try:
        ts = datetime.fromisoformat(since)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(400, "since must be an ISO-8601 timestamp") from None

    st, di = scope.state_code, scope.district_id
    zones = [z for z in db.scalars(
        services.apply_scope(select(RiskZone), RiskZone, st, di)).all()
        if z.updated_at and z.updated_at.replace(tzinfo=ts.tzinfo) > ts]
    alerts = [a for a in db.scalars(
        services.apply_scope(select(Alert), Alert, st, di)).all()
        if a.updated_at and a.updated_at.replace(tzinfo=ts.tzinfo) > ts]

    return respond({
        "since": since,
        "generated_at": utcnow().isoformat(),
        "zones": [S.risk_zone(z) for z in zones],
        "alerts": [S.alert(a) for a in alerts],
        "counts": {"zones": len(zones), "alerts": len(alerts)},
    }, case, response)


@router.post("/batch")
def batch(
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Replay a device's offline queue.

    Per-operation results, never all-or-nothing. One malformed report in a queue of
    twenty must not block the other nineteen — the device would retry the whole
    batch forever and nothing would ever land.
    """
    device_id = body.get("device_id", "unknown")
    ops = body.get("operations") or []
    results = []

    for op in ops:
        kind = (op.get("op") or "").upper()
        client_id = op.get("client_id")
        payload = op.get("payload") or {}
        payload["client_id"] = client_id
        payload["device_id"] = device_id

        if not client_id:
            results.append({"client_id": None, "status": "REJECTED",
                            "error": "client_id is required for idempotent replay"})
            continue

        seen = db.get(SyncLedger, client_id)
        if seen:
            results.append({"client_id": client_id, "status": "DUPLICATE",
                            "server_id": seen.server_id})
            continue

        try:
            if kind == "FIELD_REPORT":
                rep = _persist_report(db, payload, files=None)
                db.flush()
                results.append({"client_id": client_id, "status": "ACCEPTED",
                                "server_id": rep.id,
                                "record": S.field_report(rep, [])})
            elif kind == "ALERT_ACK":
                alert = db.get(Alert, payload.get("alert_id"))
                if not alert:
                    raise ValueError(f"Unknown alert {payload.get('alert_id')}")
                # Server wins on authority state: if it was already handled while the
                # device was dark, the queued acknowledgement is stale, not newer.
                if alert.status == "NEW":
                    from ..core import alert_engine as ae
                    ae.transition(db, alert, "ACKNOWLEDGED",
                                  payload.get("actor", device_id), "offline replay")
                db.add(SyncLedger(client_id=client_id, device_id=device_id,
                                  op=kind, server_id=alert.id))
                db.flush()
                results.append({"client_id": client_id, "status": "ACCEPTED",
                                "server_id": alert.id, "record": S.alert(alert)})
            else:
                results.append({"client_id": client_id, "status": "REJECTED",
                                "error": f"Unsupported operation {kind!r}"})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results.append({"client_id": client_id, "status": "FAILED",
                            "error": str(exc)[:200]})

    db.commit()
    summary = {
        "device_id": device_id,
        "received": len(ops),
        "accepted": sum(1 for r in results if r["status"] == "ACCEPTED"),
        "duplicates": sum(1 for r in results if r["status"] == "DUPLICATE"),
        "failed": sum(1 for r in results if r["status"] in ("FAILED", "REJECTED")),
        "server_time": utcnow().isoformat(),
        "results": results,
    }
    return respond(summary, case, response)


@router.get("/status")
def sync_status(response: Response, db: Session = Depends(get_db),
                case: str | None = Depends(get_case)):
    pending = db.scalars(
        select(IncidentReport).where(IncidentReport.sync_status == "PENDING_SYNC")
    ).all()
    return respond({
        "server_time": utcnow().isoformat(),
        "ledger_entries": db.query(SyncLedger).count(),
        "reports_pending_sync": len(pending),
        "conflict_policy": {
            "field_captured": "client wins (report body, GPS, capture time)",
            "authority_state": "server wins (alert status, verification)",
        },
    }, case, response)
