"""/api/reports — the quarterly report payload the analytics page renders.

One endpoint returns the whole report object. That is deliberate: the report is a
single publication with internally consistent figures, and assembling it from eight
independent endpoints is how a KPI grid ends up disagreeing with the chart below it.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import logging
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .. import services
from ..config import settings
from ..data.regions import DISTRICT_BY_ID, DISTRICTS
from ..deps import Session, get_case, get_db, respond
from ..models import (
    Alert,
    HistoricalIncident,
    Infrastructure,
    JobRecord,
    ModelRun,
    RiskHistory,
    RiskZone,
    Sensor,
    utcnow,
)

router = APIRouter(prefix="/api", tags=["reports"])

log = logging.getLogger("ner.reports")

PERIOD_DAYS = 90


def _scoped(rows, district_id):
    if district_id and district_id != "ALL":
        return [r for r in rows if r.district_id == district_id]
    return list(rows)


@router.get("/model/performance")
def model_performance(response: Response, db: Session = Depends(get_db),
                      case: str | None = Depends(get_case)):
    from .. import serializers as S

    run = db.scalars(select(ModelRun).order_by(ModelRun.ran_at.desc())).first()
    if not run:
        return respond({"available": False,
                        "note": "No model run registered. POST /api/model/predict to publish one."},
                       case, response)
    return respond(S.model_run(run), case, response)


@router.get("/reports/quarterly")
def quarterly(
    response: Response,
    district: str | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    did = district if district and district != "ALL" else None
    return respond(build_quarterly(db, did), case, response)


def build_quarterly(db: Session, did: str | None) -> dict:
    """The whole report as one object.

    A plain function, not just a route handler, because the HTML renderer needs the
    exact same figures. Two code paths computing "the report" is how a printed KPI
    ends up disagreeing with the same KPI on screen.
    """
    scope_label = (DISTRICT_BY_ID[did]["name"] if did and did in DISTRICT_BY_ID
                   else "North Eastern Region \u2014 all states")

    zones = _scoped(db.scalars(select(RiskZone)).all(), did)
    alerts = _scoped(db.scalars(select(Alert)).all(), did)
    incidents = _scoped(db.scalars(select(HistoricalIncident)).all(), did)
    sensors = _scoped(db.scalars(select(Sensor)).all(), did)
    infra = _scoped(db.scalars(select(Infrastructure)).all(), did)

    trend = services.risk_trend(db, did, PERIOD_DAYS)
    online = sum(1 for s in sensors if s.status == "ONLINE")
    uptime = round(online / len(sensors) * 100, 1) if sensors else 0.0
    mean_health = round(sum(s.health_score for s in sensors) / len(sensors)) if sensors else 0
    mean_response = (round(sum(i.response_time_minutes for i in incidents) / len(incidents))
                     if incidents else 0)
    detection = (round(sum(1 for i in incidents if i.predicted) / len(incidents) * 100, 1)
                 if incidents else 0.0)
    false_alarms = sum(1 for a in alerts if a.status == "RESOLVED" and a.escalation_count == 0)

    now = utcnow()
    severities = ["CRITICAL", "HIGH", "MODERATE", "INFORMATION"]

    hist_q = select(RiskHistory).where(RiskHistory.recorded_at >= now - timedelta(days=PERIOD_DAYS))
    if did:
        hist_q = hist_q.where(RiskHistory.district_id == did)
    by_day: dict[str, list[float]] = {}
    for h in db.scalars(hist_q).all():
        by_day.setdefault(h.recorded_at.date().isoformat(), []).append(h.risk_score)
    calendar = []
    for day in sorted(by_day):
        avg = round(sum(by_day[day]) / len(by_day[day]))
        calendar.append({
            "date": f"{day}T00:00:00+00:00", "risk_score": avg,
            "risk_level": ("CRITICAL" if avg >= 80 else "HIGH" if avg >= 60
                           else "MODERATE" if avg >= 35 else "LOW"),
        })

    comparison = []
    for d in (DISTRICTS if not did else [DISTRICT_BY_ID[did]]):
        dz = [z for z in db.scalars(select(RiskZone)).all() if z.district_id == d["id"]]
        comparison.append({
            "district": d["name"],
            "risk_score": round(sum(z.risk_score for z in dz) / len(dz)) if dz else 0,
            "alerts": sum(1 for a in db.scalars(select(Alert)).all() if a.district_id == d["id"]),
            "incidents": sum(1 for i in db.scalars(select(HistoricalIncident)).all()
                             if i.district_id == d["id"]),
        })
    comparison.sort(key=lambda x: -x["risk_score"])

    run = db.scalars(select(ModelRun).order_by(ModelRun.ran_at.desc())).first()

    payload = {
        "id": f"RPT-{did or 'ALL'}-{now:%Y-Q}{(now.month - 1) // 3 + 1}",
        "title": "Landslide Early Warning \u2014 Quarterly Risk Report",
        "period_label": f"{(now - timedelta(days=PERIOD_DAYS)):%B} \u2013 {now:%B %Y}",
        "period_start": (now - timedelta(days=PERIOD_DAYS)).isoformat(),
        "period_end": now.isoformat(),
        "generated_at": now.isoformat(),
        "scope": scope_label,
        "kpis": [
            {"key": "detection", "label": "Events preceded by an alert",
             "value": str(detection), "unit": "%", "higher_is_better": True,
             "note": "Share of recorded events for which an alert was already open."},
            {"key": "high-risk-events", "label": "High-risk events",
             "value": str(sum(1 for i in incidents if i.severity in ("HIGH", "CRITICAL"))),
             "higher_is_better": False},
            {"key": "alerts", "label": "Alerts generated", "value": str(len(alerts)),
             "higher_is_better": False},
            {"key": "uptime", "label": "Sensor uptime", "value": str(uptime), "unit": "%",
             "higher_is_better": True},
            {"key": "false-alarms", "label": "Alerts closed without escalation",
             "value": str(false_alarms), "higher_is_better": False,
             "note": "Proxy for false alarms until field outcomes are recorded."},
            {"key": "response", "label": "Mean response time", "value": str(mean_response),
             "unit": "min", "higher_is_better": False},
        ],
        "risk_trend": trend,
        "rainfall_vs_risk": [
            {"date": t["date"], "rainfall": t["rainfall"], "risk_score": t["risk_score"],
             "threshold": settings.t_crit_24h * 0.63}
            for t in trend
        ],
        "alerts_by_severity": [
            {"severity": s, "count": sum(1 for a in alerts if a.severity == s)}
            for s in severities
        ],
        "sensor_performance": [
            {"month": (now - timedelta(days=60 - m * 30)).strftime("%b"),
             "uptime_pct": uptime, "mean_health": mean_health}
            for m in range(3)
        ],
        "risk_calendar": calendar,
        "district_comparison": comparison[:12],
        "infrastructure_impact": [
            {"type": t,
             "exposed": sum(1 for i in infra if i.infra_type == t and i.exposure != "LOW"),
             "critical": sum(1 for i in infra if i.infra_type == t and i.exposure == "CRITICAL")}
            for t in ["HIGHWAY", "BRIDGE", "HOSPITAL", "SCHOOL", "VILLAGE"]
        ],
        "response_metrics": [
            {"label": "Mean acknowledgement time",
             "value": _mean_minutes(alerts, "acknowledged_at"), "unit": "min"},
            {"label": "Mean dispatch time",
             "value": _mean_minutes(alerts, "dispatched_at"), "unit": "min"},
            {"label": "Mean road clearance", "value": max(1, mean_response // 60), "unit": "h"},
            {"label": "Advisories delivered",
             "value": db.query(services.notify.Dispatch)
                        .filter_by(status="SENT").count(), "unit": "SMS"},
        ],
        "critical_events": [
            {"date": i.date.isoformat(),
             "title": f"{i.incident_type.replace('_', ' ').lower()} \u2014 {i.location}",
             "district": i.district, "severity": i.severity,
             "note": ("An alert was open before the event. "
                      f"Response in {i.response_time_minutes} min."
                      if i.predicted else
                      "No prior alert. Event added to the retraining set for review.")}
            for i in sorted(incidents, key=lambda x: x.date, reverse=True)
            if i.severity in ("CRITICAL", "HIGH")
        ][:6],
        "model_performance": (
            {"selected_model": run.algorithm, **run.metrics,
             "feature_importance": run.feature_importance,
             "evaluated_on": run.evaluated_on, "caveat": run.caveat}
            if run else None
        ),
        # No recommendations section. This report states what happened and what the
        # instruments recorded; deciding what to do about it is the district
        # administration's job, and a machine-authored action list printed under a
        # government letterhead invites exactly the wrong kind of deference.
        "exposure_detail": services.infrastructure_exposure(db, None, did)[:10],
        "historical_context": _historical_context(did),
        "data_confidence": settings.data_confidence,
        # Real coordinates for the report's terrain and exposure plots — the
        # server-rendered SVGs project these actual zone polygons and asset
        # points instead of drawing a fixed schematic per district.
        "zones_geo": [
            {
                "id": z.id, "name": z.name, "district": z.district,
                "lat": z.lat, "lng": z.lng,
                "risk_score": z.risk_score, "risk_level": z.risk_level,
                "slope_deg": z.slope_deg, "elevation_m": z.elevation_m,
                "geometry": z.geometry,
            }
            for z in zones
        ],
    }
    return payload


def _historical_context(district_id: str | None) -> dict:
    """Ten years of recorded regional events, from the cleaned historical dataset.

    Reported at state level because that is the resolution the dataset actually
    has — every row carries a state and a coordinate but no district. Presenting it
    as a district figure would be inventing precision the source does not contain.
    """
    from ..core import historical

    state_code = None
    if district_id and district_id in DISTRICT_BY_ID:
        state_code = DISTRICT_BY_ID[district_id]["state_code"]
    return historical.summary(state_code)


def _mean_minutes(alerts, field: str) -> int:
    deltas = []
    for a in alerts:
        t = getattr(a, field)
        if t and a.issued_at:
            deltas.append((t - a.issued_at).total_seconds() / 60)
    return round(sum(deltas) / len(deltas)) if deltas else 0


def _build_html(db: Session, district_id: str | None) -> str:
    """Render the report document for one scope."""
    from ..core import gis_store, report_builder

    payload = build_quarterly(db, district_id)
    corridor = None
    if (not district_id or district_id in ("ALL", gis_store.CORRIDOR_DISTRICT_ID)) \
            and gis_store.available():
        corridor = gis_store.corridor_summary(0)
    return report_builder.render(payload, corridor)


@router.get("/reports/render", response_class=HTMLResponse)
def render_report(
    district: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """The report as a printable document.

    Served as HTML rather than as a generated PDF: the browser's own print-to-PDF
    produces a better-typeset file than any server-side renderer we could install
    here, and it works on a machine with no LaTeX, no headless Chrome and no
    network. The stylesheet carries the print rules and page breaks.
    """
    did = district if district and district != "ALL" else None
    return HTMLResponse(_build_html(db, did))


@router.post("/reports/generate")
def generate(
    response: Response,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Generate a report for a scope and write it to the reports directory.

    Kept as a job handle rather than a synchronous download so the same contract
    survives the day a scope grows large enough that rendering genuinely takes
    minutes. At current data volumes the render finishes inside the request, so the
    job comes back DONE with a URL already attached.
    """
    scope_id = body.get("scope_id") or body.get("district") or "ALL"
    job = JobRecord(
        job_id=f"JOB-{uuid.uuid4().hex[:6].upper()}",
        kind="QUARTERLY_REPORT",
        status="RUNNING",
        scope_id=scope_id,
        fmt=body.get("format", "html"),
    )
    db.add(job)
    db.commit()

    try:
        did = scope_id if scope_id != "ALL" else None
        document = _build_html(db, did)
        out_dir = Path(settings.report_out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{job.job_id}-{scope_id}.html"
        (out_dir / filename).write_text(document, encoding="utf-8")
        job.status = "DONE"
        job.finished_at = utcnow()
        job.result_url = f"/api/reports/files/{filename}"
    except Exception as exc:  # noqa: BLE001
        # A failed report must say why. "Generation failed" sends the operator to
        # a developer; the exception text at least sends them somewhere.
        job.status = "FAILED"
        job.finished_at = utcnow()
        job.result_url = None
        log.exception("report generation failed for scope %s", scope_id)
        db.commit()
        raise HTTPException(500, f"Report generation failed: {exc}") from exc

    db.commit()
    return respond({"job_id": job.job_id, "status": job.status, "format": job.fmt,
                    "scope_id": job.scope_id, "result_url": job.result_url,
                    "view_url": f"/api/reports/render?district={scope_id}"}, case, response)


@router.get("/reports/files/{filename}", response_class=HTMLResponse)
def report_file(filename: str):
    path = (Path(settings.report_out_dir) / filename).resolve()
    root = Path(settings.report_out_dir).resolve()
    # Path containment check: a filename is user input, and `..` in it must not
    # become a file read outside the reports directory.
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, f"Report {filename} not found")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/reports/jobs/{job_id}")
def job_status(job_id: str, response: Response, db: Session = Depends(get_db),
               case: str | None = Depends(get_case)):
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return respond({"job_id": job.job_id, "status": job.status,
                    "result_url": job.result_url,
                    "created_at": job.created_at.isoformat()}, case, response)
