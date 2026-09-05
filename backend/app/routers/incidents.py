"""/api/incidents and /api/reports/field.

Field reports are treated as SIGNALS, not ground truth. They arrive unverified,
stay visually separate from sensor-derived risk, and only influence the alert
engine (rule R6) once an authority has verified them. A platform that lets an
anonymous photo trigger a public evacuation SMS is one prank away from losing the
district's trust permanently.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..config import settings
from ..data.regions import DISTRICT_BY_ID, STATE_BY_CODE
from ..deps import Scope, Session, get_case, get_db, get_scope, require_role, respond
from ..models import HistoricalIncident, IncidentReport, ReportMedia, SyncLedger, utcnow

router = APIRouter(prefix="/api", tags=["incidents"])

ALLOWED_MEDIA = {
    "image/jpeg", "image/png", "image/webp", "image/heic",
    "video/mp4", "video/quicktime", "video/webm",
}
MAX_MEDIA_BYTES = 25 * 1024 * 1024


@router.get("/incidents")
def list_incidents(
    response: Response,
    scope: Scope = Depends(get_scope),
    incident_type: str | None = Query(None),
    severity: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = services.apply_scope(select(HistoricalIncident), HistoricalIncident,
                             scope.state_code, scope.district_id)
    if incident_type:
        q = q.where(HistoricalIncident.incident_type == incident_type.upper())
    if severity:
        q = q.where(HistoricalIncident.severity == severity.upper())
    if date_from:
        q = q.where(HistoricalIncident.date >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.where(HistoricalIncident.date <= datetime.fromisoformat(date_to))
    rows = db.scalars(q.order_by(HistoricalIncident.date.desc())).all()
    return respond([S.incident(i) for i in rows], case, response)


def _attachments(db: Session, report_id: str) -> list[ReportMedia]:
    return db.scalars(select(ReportMedia).where(ReportMedia.report_id == report_id)).all()


@router.get("/reports/field")
def list_field_reports(
    response: Response,
    scope: Scope = Depends(get_scope),
    verification: str | None = Query(None),
    sync_status: str | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = services.apply_scope(select(IncidentReport), IncidentReport,
                             scope.state_code, scope.district_id)
    if verification:
        q = q.where(IncidentReport.verification == verification.upper())
    if sync_status:
        q = q.where(IncidentReport.sync_status == sync_status.upper())
    rows = db.scalars(q.order_by(IncidentReport.reported_at.desc())).all()
    return respond([S.field_report(r, _attachments(db, r.id)) for r in rows], case, response)


def _persist_report(db: Session, payload: dict, files: list[UploadFile] | None) -> IncidentReport:
    """Shared by the multipart handler and the offline batch sync."""
    client_id = payload.get("client_id")

    # Idempotency: an offline device that retries after a flaky uplink must not
    # create the same landslide report five times.
    if client_id:
        existing = db.scalars(
            select(IncidentReport).where(IncidentReport.client_id == client_id)
        ).first()
        if existing:
            return existing

    did = payload.get("district_id")
    d = DISTRICT_BY_ID.get(did)
    if not d:
        raise HTTPException(400, f"Unknown district_id {did!r}")
    state = STATE_BY_CODE[d["state_code"]]

    rid = payload.get("id") or f"FR-{uuid.uuid4().hex[:6].upper()}"
    loc = payload.get("location") or {}
    lat = payload.get("lat", loc.get("lat", d["lat"]))
    lng = payload.get("lng", loc.get("lng", d["lng"]))

    rep = IncidentReport(
        id=rid,
        client_id=client_id,
        incident_type=(payload.get("incident_type") or "CRACK").upper(),
        description=payload.get("description", ""),
        district_id=did, district=d["name"], state_code=state["code"],
        road_or_village=payload.get("road_or_village", ""),
        lat=float(lat), lng=float(lng),
        gps_accuracy_m=payload.get("gps_accuracy_m"),
        severity=(payload.get("severity") or "MODERATE").upper(),
        reporter_type=(payload.get("reporter_type") or "CITIZEN").upper(),
        reporter_name=payload.get("reporter_name") or "Anonymous",
        reporter_contact=payload.get("reporter_contact"),
        reported_at=utcnow(),
        captured_at=(datetime.fromisoformat(payload["captured_at"])
                     if payload.get("captured_at") else None),
        sync_status="SYNCED",
        verification="PENDING",
    )
    db.add(rep)
    db.flush()

    for f in files or []:
        if f.content_type not in ALLOWED_MEDIA:
            raise HTTPException(415, f"Unsupported media type {f.content_type}")
        data = f.file.read()
        if len(data) > MAX_MEDIA_BYTES:
            raise HTTPException(413, f"{f.filename} exceeds the 25 MB limit")
        os.makedirs(os.path.join(settings.media_root, rid), exist_ok=True)
        mid = uuid.uuid4().hex[:12]
        safe = os.path.basename(f.filename or f"{mid}.bin")
        path = os.path.join(settings.media_root, rid, f"{mid}_{safe}")
        with open(path, "wb") as fh:
            fh.write(data)
        db.add(ReportMedia(
            id=mid, report_id=rid,
            kind="VIDEO" if (f.content_type or "").startswith("video") else "IMAGE",
            filename=safe, content_type=f.content_type or "application/octet-stream",
            size_bytes=len(data), storage_path=path, url=f"/api/media/{rid}/{mid}_{safe}",
        ))

    if client_id:
        db.add(SyncLedger(client_id=client_id,
                          device_id=payload.get("device_id") or "unknown",
                          op="FIELD_REPORT", server_id=rid))
    return rep


@router.post("/reports/field", status_code=201)
async def submit_field_report(
    response: Response,
    incident_type: str = Form(...),
    description: str = Form(""),
    district_id: str = Form(...),
    road_or_village: str = Form(""),
    lat: float = Form(...),
    lng: float = Form(...),
    severity: str = Form("MODERATE"),
    reporter_type: str = Form("CITIZEN"),
    reporter_name: str = Form("Anonymous"),
    reporter_contact: str | None = Form(None),
    gps_accuracy_m: float | None = Form(None),
    captured_at: str | None = Form(None),
    client_id: str | None = Form(None),
    device_id: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """multipart/form-data: one `report` part plus one part per attachment."""
    payload = {
        "incident_type": incident_type, "description": description,
        "district_id": district_id, "road_or_village": road_or_village,
        "lat": lat, "lng": lng, "severity": severity,
        "reporter_type": reporter_type, "reporter_name": reporter_name,
        "reporter_contact": reporter_contact, "gps_accuracy_m": gps_accuracy_m,
        "captured_at": captured_at, "client_id": client_id, "device_id": device_id,
    }
    rep = _persist_report(db, payload, files)
    db.commit()
    return respond(S.field_report(rep, _attachments(db, rep.id)), case, response)


@router.patch("/reports/field/{report_id}/verification")
def set_verification(
    report_id: str,
    response: Response,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("DDMA")),
    case: str | None = Depends(get_case),
):
    """Authority action. Verifying a ROAD_BLOCKAGE here is what lets rule R6 fire,
    so this is a load-bearing endpoint, not bookkeeping."""
    rep = db.get(IncidentReport, report_id)
    if not rep:
        raise HTTPException(404, f"Report {report_id} not found")
    status = (body.get("verification") or "").upper()
    if status not in ("PENDING", "VERIFIED", "REJECTED"):
        raise HTTPException(400, "verification must be PENDING, VERIFIED or REJECTED")
    rep.verification = status
    rep.verified_by = body.get("actor") or user.get("sub", "authority")
    rep.verification_note = body.get("note")
    db.commit()
    return respond(S.field_report(rep, _attachments(db, rep.id)), case, response)


@router.get("/media/{report_id}/{filename}")
def get_media(report_id: str, filename: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse

    m = db.scalars(
        select(ReportMedia).where(ReportMedia.report_id == report_id)
    ).all()
    hit = next((x for x in m if os.path.basename(x.storage_path) == filename), None)
    if not hit or not os.path.exists(hit.storage_path):
        raise HTTPException(404, "Media not found")
    return FileResponse(hit.storage_path, media_type=hit.content_type)
