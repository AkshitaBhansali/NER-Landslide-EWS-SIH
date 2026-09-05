"""Alert engine.

Seven rules evaluate every zone on each risk run. Each returns a candidate or None;
candidates are then deduplicated, escalated or suppressed before anything is written.

The hard problem here is not detecting risk — the risk engine already did that. It is
deciding when a number becomes a message. Get that wrong in one direction and
districts stop reading the SMS; wrong in the other and people are not warned. The
three mechanisms that do the work:

  * COOLDOWN   - one open alert per (zone, trigger). Re-firing inside the cooldown
                 window updates the existing alert instead of creating a second one.
  * ESCALATION - if conditions worsen, the open alert's severity is raised and a new
                 dispatch goes out. The alert ID does not change, so an authority
                 tracking ALT-1004 keeps tracking ALT-1004.
  * CONFIDENCE - alerts built on unreliable sensors are flagged, not dropped. They
                 route to a human for verification instead of straight to the public.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, AlertEvent, IncidentReport, RiskZone, Sensor, SensorReading, utcnow
from .risk_engine import RECOMMENDED_ACTION, alert_tier_from_score, expected_window_hours

# Order matters: the first rule to fire supplies the trigger label.
TRIGGERS = (
    "MODEL_PROBABILITY",
    # An operator-authored rule outranks the generic environmental rules on a tie:
    # if a district office wrote a threshold for this slope, it knows something the
    # regional defaults do not.
    "CUSTOM_RULE",
    "COMBINED",
    "RAINFALL_THRESHOLD",
    "SOIL_SATURATION",
    "SLOPE_MOVEMENT",
    "ROAD_BLOCKAGE",
    "SENSOR_ANOMALY",
)

SEVERITY_ORDER = {"INFORMATION": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass
class Candidate:
    zone_id: str
    rule_id: str
    trigger: str
    severity: str
    detail: str
    score: float
    meta: dict = field(default_factory=dict)


def severity_from_level(level: str) -> str:
    """Risk LOW still produces an INFORMATION alert, never silence, when a rule fires."""
    return "INFORMATION" if level == "LOW" else level


def _title(severity: str, meta: dict | None = None) -> str:
    """A custom rule's own name is a better headline than a generic severity string —
    an operator scanning the alert list recognises "Mahur cutting - 90 mm rule"
    faster than a fourth copy of "Elevated slope failure risk"."""
    if meta and meta.get("custom_rule_name"):
        return meta["custom_rule_name"]
    return {
        "CRITICAL": "High landslide probability detected",
        "HIGH": "Elevated slope failure risk",
        "MODERATE": "Risk build-up under watch",
        "INFORMATION": "Advisory \u2014 conditions being monitored",
    }[severity]


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def rule_model_probability(zone: RiskZone) -> Candidate | None:
    """R1 — the model itself is above the dispatch cut-off."""
    if zone.risk_score < settings.dispatch_cutoff:
        return None
    return Candidate(
        zone_id=zone.id,
        rule_id="R1",
        trigger="MODEL_PROBABILITY",
        severity=severity_from_level(zone.risk_level),
        detail=(
            f"Classifier probability {zone.probability * 100:.1f}% above the "
            f"{settings.dispatch_cutoff:.0f}% dispatch cut-off"
        ),
        score=zone.risk_score,
    )


def rule_combined(zone: RiskZone, threshold_24h: float) -> Candidate | None:
    """R2 — the NER failure signature: saturated ground plus a fresh burst.

    This is the rule that matters most in this region. Neither input alone would
    fire, which is exactly why single-variable rainfall warnings miss events here.
    """
    wet = zone.soil_moisture_pct >= 70
    raining = zone.rainfall_24h_mm >= 0.7 * threshold_24h
    if not (wet and raining):
        return None
    severity = "CRITICAL" if zone.risk_score >= settings.bands.high else "HIGH"
    return Candidate(
        zone_id=zone.id,
        rule_id="R2",
        trigger="COMBINED",
        severity=severity,
        detail=(
            f"Soil moisture {zone.soil_moisture_pct:.0f}% with 24h rainfall "
            f"{zone.rainfall_24h_mm:.0f} mm against a {threshold_24h:.0f} mm threshold"
        ),
        score=zone.risk_score,
    )


def rule_rainfall(zone: RiskZone, threshold_24h: float) -> Candidate | None:
    """R3 — plain rainfall threshold breach."""
    if zone.rainfall_24h_mm < threshold_24h:
        return None
    return Candidate(
        zone_id=zone.id,
        rule_id="R3",
        trigger="RAINFALL_THRESHOLD",
        severity=severity_from_level(zone.risk_level),
        detail=(
            f"24h rainfall {zone.rainfall_24h_mm:.0f} mm against a "
            f"{threshold_24h:.0f} mm district threshold"
        ),
        score=zone.risk_score,
    )


def rule_soil_saturation(zone: RiskZone) -> Candidate | None:
    """R4 — ground at or past field capacity."""
    if zone.soil_moisture_pct < settings.soil_saturation_pct:
        return None
    return Candidate(
        zone_id=zone.id,
        rule_id="R4",
        trigger="SOIL_SATURATION",
        severity="HIGH" if zone.risk_score >= settings.bands.moderate else "MODERATE",
        detail=f"Soil moisture at {zone.soil_moisture_pct:.0f}% VWC \u2014 at or past saturation",
        score=zone.risk_score,
    )


def rule_slope_movement(db: Session, zone: RiskZone) -> Candidate | None:
    """R5 — measured ground movement.

    The only rule backed by direct observation of the failure itself rather than by
    a proxy for it. When it fires, it outranks everything: the slope is already moving.
    """
    movers = db.scalars(
        select(Sensor).where(
            Sensor.zone_id == zone.id,
            Sensor.sensor_type.in_(("TILTMETER", "EXTENSOMETER")),
            Sensor.status != "OFFLINE",
        )
    ).all()
    for s in movers:
        rows = db.scalars(
            select(SensorReading)
            .where(SensorReading.sensor_id == s.id)
            .order_by(SensorReading.timestamp.desc())
            .limit(4)
        ).all()
        if len(rows) < 4:
            continue
        vals = [r.value for r in reversed(rows)]
        delta = vals[-1] - vals[0]
        limit = settings.tilt_delta_deg if s.sensor_type == "TILTMETER" else 8.0
        if abs(delta) >= limit:
            unit = "\u00b0" if s.sensor_type == "TILTMETER" else "mm"
            return Candidate(
                zone_id=zone.id,
                rule_id="R5",
                trigger="SLOPE_MOVEMENT",
                severity="CRITICAL",
                detail=(
                    f"{s.sensor_type.title()} {s.id} moved {abs(delta):.2f}{unit} "
                    f"across three consecutive intervals"
                ),
                score=max(zone.risk_score, settings.bands.critical),
                meta={"sensor_id": s.id},
            )
    return None


def rule_road_blockage(db: Session, zone: RiskZone) -> Candidate | None:
    """R6 — a verified field report of a blocked road inside this zone's district."""
    since = utcnow() - timedelta(hours=12)
    rep = db.scalars(
        select(IncidentReport).where(
            IncidentReport.district_id == zone.district_id,
            IncidentReport.incident_type == "ROAD_BLOCKAGE",
            IncidentReport.verification == "VERIFIED",
            IncidentReport.reported_at >= since,
        ).order_by(IncidentReport.reported_at.desc())
    ).first()
    if not rep:
        return None
    return Candidate(
        zone_id=zone.id,
        rule_id="R6",
        trigger="ROAD_BLOCKAGE",
        severity="HIGH",
        detail=f"Verified field report {rep.id}: {rep.road_or_village or rep.district} blocked",
        score=max(zone.risk_score, settings.bands.high),
        meta={"report_id": rep.id},
    )


def rule_sensor_anomaly(db: Session, zone: RiskZone) -> Candidate | None:
    """R7 — the zone has gone blind.

    Not a landslide warning. It is an operational alert saying we can no longer make
    a landslide warning for this zone, which during a monsoon is its own emergency.
    """
    sensors = db.scalars(select(Sensor).where(Sensor.zone_id == zone.id)).all()
    if not sensors:
        return None
    offline = [s for s in sensors if s.status == "OFFLINE"]
    if len(offline) / len(sensors) < 0.5:
        return None
    return Candidate(
        zone_id=zone.id,
        rule_id="R7",
        trigger="SENSOR_ANOMALY",
        severity="MODERATE",
        detail=(
            f"{len(offline)} of {len(sensors)} sensors offline \u2014 risk score for this "
            f"zone is running on stale inputs"
        ),
        score=zone.risk_score,
        meta={"offline": [s.id for s in offline]},
    )


def evaluate_zone(db: Session, zone: RiskZone, threshold_24h: float) -> list[Candidate]:
    out = [
        rule_model_probability(zone),
        rule_combined(zone, threshold_24h),
        rule_rainfall(zone, threshold_24h),
        rule_soil_saturation(zone),
        rule_slope_movement(db, zone),
        rule_road_blockage(db, zone),
        rule_sensor_anomaly(db, zone),
    ]
    return [c for c in out if c is not None]


def pick_primary(cands: list[Candidate]) -> Candidate | None:
    """Highest severity wins; ties break on the TRIGGERS order."""
    if not cands:
        return None
    return sorted(
        cands,
        key=lambda c: (-SEVERITY_ORDER[c.severity], TRIGGERS.index(c.trigger)),
    )[0]


# --------------------------------------------------------------------------- #
# Persistence: dedup / escalate / create
# --------------------------------------------------------------------------- #
def _next_alert_id(db: Session) -> str:
    n = db.query(Alert).count()
    return f"ALT-{1000 + n}"


def log(db: Session, alert_id: str, event: str, actor: str = "system", detail: str = "") -> None:
    db.add(AlertEvent(alert_id=alert_id, event=event, actor=actor, detail=detail))


def alert_class(trigger: str, meta: dict | None = None) -> str:
    """Two kinds of alert that must never be merged.

    HAZARD says the slope may fail. OPERATIONAL says we have lost the ability to
    tell. Collapsing them would let a sensor outage overwrite a landslide warning
    on the same zone, which is the worst possible failure of this system.

    A custom rule carries its own class, because whether it is a hazard rule or an
    operational one depends on the parameters the operator chose, not on the fact
    that it is custom.
    """
    if trigger == "CUSTOM_RULE" and meta:
        return meta.get("alert_class", "HAZARD")
    return "OPERATIONAL" if trigger == "SENSOR_ANOMALY" else "HAZARD"


def upsert_alert(db: Session, zone: RiskZone, cand: Candidate, roads: list[str],
                 villages: list[str]) -> tuple[Alert, str]:
    """Returns (alert, action) where action is CREATED | ESCALATED | SUPPRESSED.

    Deduplication is per (zone, class), NOT per (zone, trigger). One hillside
    produces one hazard alert, whatever combination of rules happens to be firing
    on it. Keying on trigger looked tidier but meant a zone where rainfall, soil
    saturation and the model all fired generated three alerts for one slope — and
    an alerts page that lists the same hillside three times is a page nobody reads.
    """
    cls = alert_class(cand.trigger, cand.meta)
    candidates = db.scalars(
        select(Alert).where(Alert.zone_id == zone.id).order_by(Alert.issued_at.desc())
    ).all()
    same_class = [a for a in candidates if (a.alert_class or alert_class(a.trigger)) == cls]
    open_alert = next((a for a in same_class if a.status != "RESOLVED"), None)

    # Re-arm window: after an alert is resolved, hold off recreating one for the
    # same zone for the cooldown period. Without this, resolving an alert on a slope
    # that is still wet immediately spawns a replacement, and the console fights the
    # operator instead of helping them.
    if open_alert is None:
        recent_resolved = next((a for a in same_class if a.status == "RESOLVED"), None)
        if recent_resolved and recent_resolved.resolved_at:
            resolved_at = recent_resolved.resolved_at
            if resolved_at.tzinfo is None:
                resolved_at = resolved_at.replace(tzinfo=timezone.utc)
            rearm = utcnow() - timedelta(minutes=settings.alert_cooldown_minutes)
            if resolved_at >= rearm and SEVERITY_ORDER[cand.severity] <= SEVERITY_ORDER[
                recent_resolved.severity
            ]:
                return recent_resolved, "SUPPRESSED"

    low_conf = zone.sensor_confidence < settings.low_confidence_floor
    tier = cand.meta.get("tier") or alert_tier_from_score(cand.score)

    if open_alert:
        worse = SEVERITY_ORDER[cand.severity] > SEVERITY_ORDER[open_alert.severity]
        if worse:
            prev = open_alert.severity
            open_alert.severity = cand.severity
            open_alert.tier = tier
            open_alert.title = _title(cand.severity, cand.meta)
            open_alert.risk_score = cand.score
            open_alert.probability = zone.probability
            # The dominant rule can change as conditions evolve; the alert should
            # say why it is firing NOW, not why it first fired.
            open_alert.trigger = cand.trigger
            open_alert.rule_id = cand.rule_id
            open_alert.trigger_detail = cand.detail
            open_alert.custom_rule_id = cand.meta.get("custom_rule_id")
            open_alert.expected_window_hours = expected_window_hours(cand.severity) or 24
            open_alert.recommended_action = RECOMMENDED_ACTION.get(cand.severity, "")
            open_alert.escalation_count += 1
            open_alert.low_confidence = low_conf
            # Escalation reopens a handled alert: the situation changed after sign-off.
            if open_alert.status in ("ACKNOWLEDGED", "IN_PROGRESS"):
                open_alert.status = "IN_PROGRESS"
            log(db, open_alert.id, "ESCALATED", detail=f"{prev} -> {cand.severity}: {cand.detail}")
            return open_alert, "ESCALATED"

        # Same or lower severity: keep the evidence current but send nothing new.
        # Re-notifying on every cycle for an unchanged situation is precisely how a
        # district learns to mute the sender.
        open_alert.risk_score = cand.score
        open_alert.probability = zone.probability

        # A custom rule that matched an already-open alert is not a non-event. The
        # operator who wrote that rule needs to see that it fired, and on what — but
        # a second alert for the same hillside is exactly the duplication the
        # deduplication rule exists to prevent. So the match is recorded against the
        # open alert instead of raising a new one.
        if cand.trigger == "CUSTOM_RULE":
            note_custom_match(db, open_alert, cand)
        elif cand.trigger == open_alert.trigger:
            # Refresh the evidence only when it is evidence for the SAME rule. A
            # lower-severity candidate from a different rule must not overwrite the
            # reason text, or the alert ends up labelled COMBINED/R2 while its
            # stated reason quotes the classifier — and an operator who cannot trust
            # the "why" line stops reading it.
            open_alert.trigger_detail = cand.detail
        return open_alert, "SUPPRESSED"

    alert = Alert(
        id=_next_alert_id(db),
        severity=cand.severity,
        tier=tier,
        title=_title(cand.severity, cand.meta),
        zone_id=zone.id,
        location=zone.name,
        district_id=zone.district_id,
        district=zone.district,
        state_code=zone.state_code,
        lat=zone.lat,
        lng=zone.lng,
        issued_at=utcnow(),
        risk_score=cand.score,
        probability=zone.probability,
        trigger=cand.trigger,
        trigger_detail=cand.detail,
        rule_id=cand.rule_id,
        alert_class=cls,
        custom_rule_id=cand.meta.get("custom_rule_id"),
        expected_window_hours=expected_window_hours(cand.severity) or 24,
        affected_roads=roads,
        affected_villages=villages,
        population_affected=zone.population,
        recommended_action=RECOMMENDED_ACTION.get(cand.severity, ""),
        status="NEW",
        sensor_confidence=zone.sensor_confidence,
        low_confidence=low_conf,
    )
    db.add(alert)
    db.flush()
    log(db, alert.id, "CREATED", detail=f"{cand.rule_id} {cand.trigger}: {cand.detail}")
    return alert, "CREATED"


def note_custom_match(db: Session, alert: Alert, cand: Candidate) -> bool:
    """Record that a custom rule matched, against the alert already covering the zone.

    A custom rule frequently matches a slope that a built-in rule is already
    shouting about, and `pick_primary` keeps only the single most severe candidate.
    Without this, the operator who wrote the rule sees "matched 4 zones" on the
    rules page and an empty list of alerts underneath it, and reasonably concludes
    the feature is broken. Recording the match on the existing alert keeps one
    alert per hillside while preserving the audit trail of what fired and why.

    Returns True if a new event was written (matches are recorded once per alert,
    not once per cycle, or the timeline becomes unreadable within a day).
    """
    rule_id = cand.meta.get("custom_rule_id")
    if not rule_id:
        return False
    already = db.scalars(
        select(AlertEvent).where(
            AlertEvent.alert_id == alert.id,
            AlertEvent.event == "CUSTOM_RULE_MATCHED",
            AlertEvent.detail.like(f"{rule_id}:%"),
        )
    ).first()
    if already:
        return False
    log(db, alert.id, "CUSTOM_RULE_MATCHED", detail=f"{rule_id}: {cand.detail}")
    # Deliberately NOT stamping alert.custom_rule_id here. That column means "this
    # rule raised this alert", and it gates whether a dashboard-only rule suppresses
    # dispatch. Stamping it on a match would mislabel an alert R2 raised as one the
    # operator's rule raised, and could silence a hazard SMS as a side effect.
    return True


def auto_resolve_stale(db: Session) -> int:
    """Close alerts whose zone has fallen back below the cut-off and stayed there.

    Without this, an operations console fills with alerts nobody closed and the
    critical banner stops meaning anything.
    """
    cutoff = utcnow() - timedelta(hours=settings.auto_resolve_after_hours)
    open_alerts = db.scalars(select(Alert).where(Alert.status != "RESOLVED")).all()
    closed = 0
    for a in open_alerts:
        zone = db.get(RiskZone, a.zone_id)
        if zone is None:
            continue
        issued = a.issued_at.replace(tzinfo=timezone.utc) if a.issued_at.tzinfo is None else a.issued_at
        if zone.risk_score < settings.dispatch_cutoff * 0.8 and issued < cutoff:
            a.status = "RESOLVED"
            a.resolved_at = utcnow()
            log(db, a.id, "AUTO_RESOLVED", detail="Zone below cut-off for the resolve window")
            closed += 1
    return closed


def transition(db: Session, alert: Alert, to: str, actor: str, note: str = "") -> Alert:
    """Enforce the lifecycle. Illegal jumps raise rather than silently corrupting state."""
    allowed = {
        "NEW": {"ACKNOWLEDGED", "RESOLVED"},
        "ACKNOWLEDGED": {"IN_PROGRESS", "RESOLVED"},
        "IN_PROGRESS": {"RESOLVED"},
        "RESOLVED": set(),
    }
    if to not in allowed[alert.status]:
        raise ValueError(f"Cannot move alert {alert.id} from {alert.status} to {to}")

    alert.status = to
    now = utcnow()
    if to == "ACKNOWLEDGED":
        alert.acknowledged_by = actor
        alert.acknowledged_at = now
    elif to == "IN_PROGRESS":
        alert.dispatched_at = now
    elif to == "RESOLVED":
        alert.resolved_at = now
    log(db, alert.id, to, actor=actor, detail=note)
    return alert


def new_uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
