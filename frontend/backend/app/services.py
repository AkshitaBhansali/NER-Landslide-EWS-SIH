"""Service layer — the orchestration that sits between the engines and the routers.

`run_risk_cycle` is the heartbeat of the platform and the single place where
sensors -> risk -> alerts -> delivery actually happens. Everything else in this file
is read-side aggregation for the console.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .core import alert_engine as ae
from .core import custom_alerts as ca
from .core import ml_model
from .core import notify
from .core.risk_engine import (
    RECOMMENDED_ACTION,
    expected_window_hours,
    risk_level_from_score,
    score_zone,
)
from .core.sensor_health import compute_health, zone_confidence
from .models import (
    Alert,
    CustomAlertRule,
    District,
    HistoricalIncident,
    IncidentReport,
    Infrastructure,
    Notification,
    RiskHistory,
    RiskZone,
    Road,
    Sensor,
    SensorReading,
    Village,
    WeatherObservation,
    utcnow,
)


def scope_clause(model, state_code: str | None, district_id: str | None):
    if district_id and district_id != "ALL":
        return model.district_id == district_id
    if state_code and state_code != "ALL":
        return model.state_code == state_code
    return None


def apply_scope(q, model, state_code: str | None, district_id: str | None):
    c = scope_clause(model, state_code, district_id)
    return q.where(c) if c is not None else q


# --------------------------------------------------------------------------- #
# The cycle
# --------------------------------------------------------------------------- #
def refresh_sensor_health(db: Session, sensor: Sensor, now: datetime | None = None) -> None:
    now = now or utcnow()
    window = now - timedelta(hours=24)
    rows = db.scalars(
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor.id, SensorReading.timestamp >= window)
        .order_by(SensorReading.timestamp)
    ).all()
    values = [r.value for r in rows]
    expected = max(1, int(86400 / max(sensor.expected_interval_s, 1)))
    h = compute_health(
        sensor_type=sensor.sensor_type,
        values=values,
        expected_samples=expected,
        battery_pct=sensor.battery_pct,
        rssi_dbm=sensor.rssi_dbm,
        last_seen=sensor.last_seen,
        expected_interval_s=sensor.expected_interval_s,
        now=now,
    )
    sensor.health_score = h.score
    sensor.status = h.status
    sensor.health_sub_scores = h.sub_scores
    sensor.maintenance_note = h.note
    if values:
        sensor.reading = values[-1]


def published_recently(zone: RiskZone) -> bool:
    """True while an externally published prediction still owns this zone's score."""
    stamp = zone.model_published_at
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return utcnow() - stamp < timedelta(minutes=settings.model_publish_ttl_minutes)


def rescore_zone(db: Session, zone: RiskZone) -> None:
    """Recompute one zone from its current inputs.

    This used to return early for any zone whose `source` was `ML_MODEL`, on the
    reasoning that a published model score is authoritative and must not be
    overwritten. That was safe only while nothing ever published one. With
    inference now running in-process every cycle, the early return would freeze the
    zone permanently: its rainfall, soil moisture and sensor confidence would stop
    being refreshed the moment the classifier first won, and the model would then be
    fed its own stale inputs on the next tick.

    So the inputs and the rule score are always recomputed here. Model precedence is
    applied afterwards, in `ml_model.score_zones`, which re-runs on the refreshed
    inputs and keeps whichever assessment is more severe. The ordering does the work
    that the early return was trying to do, without the feedback loop.
    """

    wx = db.scalars(
        select(WeatherObservation)
        .where(WeatherObservation.district_id == zone.district_id)
        .order_by(WeatherObservation.observed_at.desc())
    ).first()
    if wx:
        zone.rainfall_24h_mm = wx.rainfall_24h_mm
        zone.rainfall_72h_mm = wx.rainfall_72h_mm
        zone.rainfall_7d_mm = wx.rainfall_7d_mm

    # Prefer live probes over the seeded value when a soil-moisture sensor is healthy.
    probes = db.scalars(
        select(Sensor).where(
            Sensor.zone_id == zone.id,
            Sensor.sensor_type == "SOIL_MOISTURE",
            Sensor.status == "ONLINE",
        )
    ).all()
    if probes:
        zone.soil_moisture_pct = round(sum(p.reading for p in probes) / len(probes), 1)

    # Inputs above are refreshed unconditionally. The score below is not: a
    # prediction an external pipeline deliberately published stays authoritative for
    # a bounded window, which is the contract /api/model/predict advertises. The
    # window is bounded so that a dead publisher cannot leave a stale number on the
    # console forever presenting itself as current.
    if published_recently(zone):
        return

    res = score_zone(
        slope_deg=zone.slope_deg, soil_type=zone.soil_type, landcover=zone.landcover,
        elevation_m=zone.elevation_m, aspect_deg=zone.aspect_deg,
        rainfall_24h_mm=zone.rainfall_24h_mm, rainfall_72h_mm=zone.rainfall_72h_mm,
        rainfall_7d_mm=zone.rainfall_7d_mm, soil_moisture_pct=zone.soil_moisture_pct,
        antecedent_precip_index=zone.antecedent_precip_index,
        sensor_confidence=zone.sensor_confidence,
    )
    zone.lsi, zone.ti = res.lsi, res.ti
    zone.risk_score = res.risk_score
    zone.risk_level = res.risk_level
    zone.alert_tier = res.alert_tier
    zone.probability = res.probability
    zone.contributing_factors = res.contributing_factors
    zone.expected_window_hours = expected_window_hours(res.risk_level)
    zone.recommended_action = RECOMMENDED_ACTION[res.risk_level]

    sensors = db.scalars(select(Sensor).where(Sensor.zone_id == zone.id)).all()
    zone.sensor_confidence = zone_confidence([s.health_score for s in sensors])


def run_risk_cycle(db: Session, send: bool = True) -> dict:
    """One full pass: health -> risk -> alerts -> dispatch -> history.

    Ordering is not arbitrary. Health must be current before risk, because
    confidence gates who gets warned. Alerts must be written before dispatch, so a
    crash between the two leaves a recorded alert with an unsent message rather than
    a message with no record of why it was sent.
    """
    now = utcnow()

    for s in db.scalars(select(Sensor)).all():
        refresh_sensor_health(db, s, now)
    db.flush()

    zones = db.scalars(select(RiskZone)).all()
    for z in zones:
        rescore_zone(db, z)
    db.flush()

    thresholds = {
        d.id: d.alert_threshold_24h for d in db.scalars(select(District)).all()
    }

    # Classifier inference runs after the rules have scored every zone and before
    # any alert is evaluated. Order matters: the model needs the rainfall
    # accumulations the rule pass just refreshed, and the alert engine must see
    # whichever score actually won.
    ml_summary = ml_model.score_zones(db, zones)

    # Operator-authored rules are loaded once and evaluated alongside R1-R7 rather
    # than in a second pass, so a custom rule competes for primacy on equal terms
    # instead of always losing to, or always overriding, the built-in rules.
    custom_rules = db.scalars(
        select(CustomAlertRule).where(CustomAlertRule.enabled.is_(True))
    ).all()
    fired_rules: dict[str, list[str]] = {}

    created = escalated = suppressed = 0
    new_alerts: list[Alert] = []
    for z in zones:
        cands = ae.evaluate_zone(db, z, thresholds.get(z.district_id, 95.0))
        custom_cands = ca.evaluate_zone(db, z, custom_rules) if custom_rules else []
        for c in custom_cands:
            fired_rules.setdefault(c.meta["custom_rule_id"], []).append(z.id)
        cands.extend(custom_cands)
        primary = ae.pick_primary(cands)
        if not primary:
            continue
        roads = [r.name for r in db.scalars(
            select(Road).where(Road.district_id == z.district_id)).all()]
        villages = [v.name for v in db.scalars(
            select(Village).where(Village.district_id == z.district_id)).all()][:3]
        alert, action = ae.upsert_alert(db, z, primary, roads, villages)

        # Custom rules that matched but were outranked still get recorded against
        # the alert covering this zone. `pick_primary` keeps one candidate; it must
        # not silently discard the evidence that an operator's own rule agreed.
        for c in custom_cands:
            if c is not primary:
                ae.note_custom_match(db, alert, c)

        alert.contributing_rules = [
            {"rule_id": c.rule_id, "trigger": c.trigger, "severity": c.severity,
             "detail": c.detail, "primary": c is primary}
            for c in sorted(cands, key=lambda x: x is not primary)
        ]

        if action == "CREATED":
            created += 1
            new_alerts.append(alert)
        elif action == "ESCALATED":
            escalated += 1
            new_alerts.append(alert)
        else:
            suppressed += 1

    now_ts = utcnow()
    for rule in custom_rules:
        rule.last_evaluated_at = now_ts
        if rule.id in fired_rules:
            ca.record_fire(rule, fired_rules[rule.id])

    resolved = ae.auto_resolve_stale(db)
    db.flush()

    # GREEN is "no message sent" in the methodology note's tier table, and
    # notify.queue_for_alert already honours that. The only extra gate is a custom
    # rule marked dashboard-only: an operator experimenting with a threshold should
    # be able to see it fire without an SMS reaching a district magistrate.
    silent_rules = {r.id for r in custom_rules if not r.notify}
    queued = 0
    for a in new_alerts:
        if a.custom_rule_id and a.custom_rule_id in silent_rules:
            continue
        queued += len(notify.queue_for_alert(db, a))
    db.flush()

    delivery = notify.flush_queue(db) if send else {}

    for z in zones:
        db.add(RiskHistory(
            zone_id=z.id, district_id=z.district_id, recorded_at=now,
            risk_score=z.risk_score, risk_level=z.risk_level,
            rainfall_24h_mm=z.rainfall_24h_mm, soil_moisture_pct=z.soil_moisture_pct,
        ))

    if created:
        db.add(Notification(
            id=ae.new_uid("N"), category="SYSTEM", title="Risk cycle completed",
            body=f"{created} new alert(s), {escalated} escalated, {resolved} auto-resolved.",
            created_at=now, read=False, href="/alerts",
        ))

    db.commit()
    return {
        "ran_at": now.isoformat(),
        "zones_scored": len(zones),
        "alerts_created": created,
        "alerts_escalated": escalated,
        "alerts_suppressed": suppressed,
        "alerts_auto_resolved": resolved,
        "model": ml_summary,
        "custom_rules_evaluated": len(custom_rules),
        "custom_rules_fired": len(fired_rules),
        "dispatches_queued": queued,
        "delivery": delivery,
    }


# --------------------------------------------------------------------------- #
# Read-side aggregation
# --------------------------------------------------------------------------- #
def risk_summary(db: Session, state_code: str | None, district_id: str | None) -> dict:
    zq = apply_scope(select(RiskZone), RiskZone, state_code, district_id)
    zones = db.scalars(zq).all()

    aq = apply_scope(select(Alert), Alert, state_code, district_id)
    alerts = [a for a in db.scalars(aq).all() if a.status != "RESOLVED"]

    sq = apply_scope(select(Sensor), Sensor, state_code, district_id)
    sensors = db.scalars(sq).all()

    rq = apply_scope(select(Road), Road, state_code, district_id)
    roads = db.scalars(rq).all()

    dids = {z.district_id for z in zones}
    wx = [w for w in db.scalars(select(WeatherObservation)).all() if w.district_id in dids]

    if zones:
        mean = sum(z.risk_score for z in zones) / len(zones)
        peak = max(z.risk_score for z in zones)
        # Peak-weighted: one critical slope in a quiet district is the story, and a
        # plain average would bury it.
        regional = round(min(100, mean * 0.45 + peak * 0.55))
    else:
        regional = 0

    weather_level = "LOW"
    if wx:
        worst = max(w.rainfall_24h_mm / max(w.alert_threshold_24h, 1) for w in wx)
        weather_level = risk_level_from_score(min(100, worst * 72))

    pending = db.scalar(
        select(func.count()).select_from(IncidentReport)
        .where(IncidentReport.verification == "PENDING")
    ) or 0

    return {
        "regional_risk_score": regional,
        "regional_risk_level": risk_level_from_score(regional),
        "active_alerts": len(alerts),
        "critical_alerts": sum(1 for a in alerts if a.severity == "CRITICAL"),
        "high_risk_zones": sum(1 for z in zones if z.risk_level in ("HIGH", "CRITICAL")),
        "total_zones": len(zones),
        "sensors_online": sum(1 for s in sensors if s.status == "ONLINE"),
        "sensors_degraded": sum(1 for s in sensors if s.status == "DEGRADED"),
        "sensors_offline": sum(1 for s in sensors if s.status == "OFFLINE"),
        "blocked_roads": sum(1 for r in roads if r.status == "BLOCKED"),
        "at_risk_roads": sum(1 for r in roads if r.status in ("AT_RISK", "RESTRICTED")),
        "reports_pending_verification": pending,
        "weather_risk_level": weather_level,
        "population_exposed": sum(
            z.population for z in zones if z.risk_level in ("HIGH", "CRITICAL")
        ),
        "updated_at": utcnow().isoformat(),
        "data_freshness_minutes": 3,
        "data_confidence": settings.data_confidence,
    }


def pipeline_status(db: Session, state_code: str | None, district_id: str | None) -> dict:
    sensors = db.scalars(apply_scope(select(Sensor), Sensor, state_code, district_id)).all()
    zones = db.scalars(apply_scope(select(RiskZone), RiskZone, state_code, district_id)).all()
    incidents = db.scalars(
        apply_scope(select(HistoricalIncident), HistoricalIncident, state_code, district_id)
    ).all()
    return {
        "sensors_reporting": sum(1 for s in sensors if s.status != "OFFLINE"),
        "sensors_total": len(sensors),
        "mean_sensor_health": round(
            sum(s.health_score for s in sensors) / len(sensors)) if sensors else 0,
        "zones_scored": len(zones),
        "mean_confidence": round(
            sum(z.sensor_confidence for z in zones) / len(zones)) if zones else 0,
        "events_preceded_by_alert": round(
            sum(1 for i in incidents if i.predicted) / len(incidents) * 100, 1
        ) if incidents else 0.0,
    }


def risk_trend(db: Session, district_id: str | None, days: int = 30) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    q = select(
        func.date(RiskHistory.recorded_at).label("d"),
        func.avg(RiskHistory.risk_score),
        func.avg(RiskHistory.rainfall_24h_mm),
    ).where(RiskHistory.recorded_at >= since).group_by("d").order_by("d")
    if district_id and district_id != "ALL":
        q = q.where(RiskHistory.district_id == district_id)

    out = []
    for day, score, rain in db.execute(q).all():
        s = round(score or 0)
        out.append({
            "date": f"{day}T00:00:00+00:00",
            "risk_score": s,
            "rainfall": round(rain or 0, 1),
            "alerts": max(0, round((s - 45) / 9)),
        })
    return out


def sensor_fleet_summary(db: Session, state_code: str | None, district_id: str | None) -> dict:
    sensors = db.scalars(apply_scope(select(Sensor), Sensor, state_code, district_id)).all()
    online = sum(1 for s in sensors if s.status == "ONLINE")
    return {
        "total": len(sensors),
        "online": online,
        "degraded": sum(1 for s in sensors if s.status == "DEGRADED"),
        "offline": sum(1 for s in sensors if s.status == "OFFLINE"),
        "low_battery": sum(1 for s in sensors if s.battery_pct < 25),
        "comm_failures": sum(1 for s in sensors if s.rssi_dbm < -105),
        "mean_health": round(
            sum(s.health_score for s in sensors) / len(sensors)) if sensors else 0,
        "uptime_pct": round(online / len(sensors) * 100, 1) if sensors else 0.0,
    }


def system_status(db: Session) -> dict:
    last = db.scalars(
        select(RiskHistory).order_by(RiskHistory.recorded_at.desc())
    ).first()
    stale_sensors = db.scalar(
        select(func.count()).select_from(Sensor).where(Sensor.status == "OFFLINE")
    ) or 0
    total_sensors = db.scalar(select(func.count()).select_from(Sensor)) or 1
    queued = db.scalar(
        select(func.count()).select_from(notify.Dispatch)
        .where(notify.Dispatch.status.in_(("QUEUED", "DEFERRED")))
    ) or 0

    services = [
        {"name": "API", "status": "OPERATIONAL"},
        {"name": "Risk engine", "status": "OPERATIONAL" if last else "DEGRADED",
         "last_run": last.recorded_at.isoformat() if last else None},
        {"name": "Sensor ingest",
         "status": "DEGRADED" if stale_sensors / total_sensors > 0.3 else "OPERATIONAL",
         "detail": f"{stale_sensors}/{total_sensors} sensors offline"},
        {"name": "Alert delivery",
         "status": "DEGRADED" if queued > 50 else "OPERATIONAL",
         "detail": f"{queued} messages queued", "provider": settings.sms_provider},
        {"name": "Weather ingest",
         "status": "OPERATIONAL" if settings.imd_api_base else "PLACEHOLDER",
         "detail": "IMD API not configured" if not settings.imd_api_base else "IMD live"},
    ]
    degraded = [s for s in services if s["status"] != "OPERATIONAL"]
    return {
        "status": "DEGRADED" if degraded else "OPERATIONAL",
        "version": settings.version,
        "environment": settings.env,
        "data_confidence": settings.data_confidence,
        "services": services,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def infrastructure_exposure(db: Session, state_code: str | None,
                            district_id: str | None) -> list[dict]:
    """risk x importance. Which asset do you send the one available crew to?"""
    rows = db.scalars(
        apply_scope(select(Infrastructure), Infrastructure, state_code, district_id)
    ).all()
    weights = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.55, "LOW": 0.3}
    scores = {"CRITICAL": 90, "HIGH": 70, "MODERATE": 45, "LOW": 20}
    out = []
    for i in rows:
        raw = scores.get(i.risk_level, 20) * weights.get(i.importance, 0.5)
        out.append({
            "id": i.id, "name": i.name, "type": i.infra_type,
            "district_id": i.district_id, "district": i.district,
            "state_code": i.state_code,
            "location": {"lat": i.lat, "lng": i.lng},
            "risk_level": i.risk_level, "importance": i.importance,
            "exposure": i.exposure, "exposure_score": round(raw, 1),
            "population_served": i.population_served,
        })
    return sorted(out, key=lambda x: -x["exposure_score"])
