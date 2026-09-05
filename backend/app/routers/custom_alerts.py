"""/api/alerts/custom — operator-authored threshold rules.

CRUD plus two endpoints that exist because a rule builder without them is a
guessing game:

  * `/catalogue` — the parameter, operator and tier vocabulary, served from the
    engine itself. The UI never hard-codes a parameter list, so adding a parameter
    to `core/custom_alerts.py` makes it appear in the builder with no frontend
    change.
  * `/preview` — evaluates an unsaved draft against live zone state and reports
    which zones it would match right now. Writing a threshold blind and waiting for
    the next monsoon to discover it was an order of magnitude off is not a workflow.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select

from .. import serializers as S
from .. import services
from ..core import custom_alerts as ca
from ..deps import Scope, Session, get_case, get_db, get_scope, require_role, respond
from ..models import Alert, AlertEvent, CustomAlertRule, RiskZone, utcnow

router = APIRouter(prefix="/api/alerts/custom", tags=["custom alerts"])

VALID_SEVERITIES = {"AUTO", "INFORMATION", "MODERATE", "HIGH", "CRITICAL"}
VALID_SCOPES = {"ALL", "STATE", "DISTRICT", "ZONE"}


def _new_id() -> str:
    return f"CR-{uuid.uuid4().hex[:6].upper()}"


def _validate(payload: dict, partial: bool = False) -> dict:
    """Reject a malformed rule at the door.

    A rule that silently never matches is worse than a rejected one: the operator
    believes a slope is being watched when nothing is watching it.
    """
    out: dict = {}

    if "name" in payload or not partial:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "A rule needs a name")
        out["name"] = name[:160]

    if "conditions" in payload or not partial:
        conds = payload.get("conditions") or []
        if not isinstance(conds, list) or not conds:
            raise HTTPException(400, "A rule needs at least one condition")
        clean = []
        for c in conds:
            key = c.get("parameter")
            param = ca.PARAM_BY_KEY.get(key)
            if param is None:
                raise HTTPException(400, f"Unknown parameter '{key}'")
            op = (c.get("operator") or "GTE").upper()
            if op not in ca.OPERATORS:
                raise HTTPException(400, f"Unknown operator '{op}'")
            if c.get("value") in (None, ""):
                raise HTTPException(400, f"{param.label} needs a threshold value")
            if op == "BETWEEN" and c.get("value2") in (None, ""):
                raise HTTPException(400, f"{param.label} needs an upper bound")
            entry = {"parameter": key, "operator": op, "value": c["value"]}
            if op == "BETWEEN":
                entry["value2"] = c["value2"]
            clean.append(entry)
        out["conditions"] = clean

    if "scope_type" in payload or not partial:
        scope_type = (payload.get("scope_type") or "ALL").upper()
        if scope_type not in VALID_SCOPES:
            raise HTTPException(400, f"Unknown scope '{scope_type}'")
        out["scope_type"] = scope_type
        scope_id = payload.get("scope_id") or "ALL"
        if scope_type != "ALL" and scope_id in (None, "", "ALL"):
            raise HTTPException(400, f"A {scope_type.lower()}-scoped rule needs a {scope_type.lower()}")
        out["scope_id"] = scope_id

    if "severity" in payload:
        sev = (payload.get("severity") or "AUTO").upper()
        if sev not in VALID_SEVERITIES:
            raise HTTPException(400, f"Unknown severity '{sev}'")
        out["severity"] = sev

    for key in ("description", "created_by"):
        if key in payload:
            out[key] = str(payload[key])[:500]
    if "match" in payload:
        out["match"] = "ANY" if str(payload["match"]).upper() == "ANY" else "ALL"
    if "alert_class" in payload:
        cls = str(payload["alert_class"]).upper()
        out["alert_class"] = cls if cls in ("HAZARD", "OPERATIONAL", "AUTO") else "AUTO"
    if "enabled" in payload:
        out["enabled"] = bool(payload["enabled"])
    if "notify" in payload:
        out["notify"] = bool(payload["notify"])
    if "cooldown_minutes" in payload:
        try:
            out["cooldown_minutes"] = max(0, int(payload["cooldown_minutes"]))
        except (TypeError, ValueError):
            raise HTTPException(400, "Cooldown must be a whole number of minutes")
    return out


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
@router.get("/catalogue")
def catalogue(response: Response, case: str | None = Depends(get_case)):
    return respond(ca.catalogue(), case, response)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
@router.get("")
def list_rules(
    response: Response,
    enabled: bool | None = Query(None),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    q = select(CustomAlertRule)
    if enabled is not None:
        q = q.where(CustomAlertRule.enabled.is_(enabled))
    rules = db.scalars(q.order_by(CustomAlertRule.created_at.desc())).all()
    return respond([S.custom_rule(r) for r in rules], case, response)


@router.post("", status_code=201)
def create_rule(
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    fields = _validate(payload)
    rule = CustomAlertRule(id=_new_id(), **fields)
    db.add(rule)
    db.commit()
    return respond(S.custom_rule(rule), case, response)


@router.get("/{rule_id}")
def get_rule(rule_id: str, response: Response, db: Session = Depends(get_db),
             case: str | None = Depends(get_case)):
    rule = db.get(CustomAlertRule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return respond(S.custom_rule(rule), case, response)


@router.patch("/{rule_id}")
def update_rule(
    rule_id: str,
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    rule = db.get(CustomAlertRule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    for key, value in _validate(payload, partial=True).items():
        setattr(rule, key, value)
    db.commit()
    return respond(S.custom_rule(rule), case, response)


@router.delete("/{rule_id}", status_code=200)
def delete_rule(
    rule_id: str,
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    rule = db.get(CustomAlertRule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    # Alerts this rule raised are deliberately left in place. Deleting the rule
    # must not erase the record that a warning was issued.
    db.delete(rule)
    db.commit()
    return respond({"deleted": rule_id, "alerts_retained": True}, case, response)


# --------------------------------------------------------------------------- #
# Preview and results
# --------------------------------------------------------------------------- #
@router.post("/preview")
def preview(
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Evaluate an unsaved draft against current zone state."""
    fields = _validate(payload)
    draft = CustomAlertRule(
        id="DRAFT", name=fields.get("name", "Draft rule"),
        conditions=fields["conditions"], match=fields.get("match", "ALL"),
        scope_type=fields.get("scope_type", "ALL"), scope_id=fields.get("scope_id", "ALL"),
        severity=fields.get("severity", "AUTO"), alert_class=fields.get("alert_class", "AUTO"),
        enabled=True, notify=False, cooldown_minutes=0, trigger_count=0,
    )

    zones = db.scalars(select(RiskZone).order_by(RiskZone.risk_score.desc())).all()
    matches, evaluated = [], 0
    for z in zones:
        if not ca.rule_applies_to(draft, z):
            continue
        evaluated += 1
        facts = ca.zone_facts(db, z)
        ok, evidence = ca.evaluate_rule(draft, z, facts)
        if not ok:
            continue
        tier, auto_sev, status = ca.tier_for(z.risk_score)
        matches.append({
            "zone_id": z.id, "zone": z.name,
            "district": z.district, "district_id": z.district_id,
            "risk_score": z.risk_score, "risk_level": z.risk_level,
            "tier": tier, "tier_status": status,
            "severity": auto_sev if draft.severity == "AUTO" else draft.severity,
            "evidence": evidence,
        })

    return respond({
        "zones_in_scope": evaluated,
        "zones_matched": len(matches),
        "alert_class": ca.infer_class(draft),
        "matches": matches[:25],
        "note": (
            "Green-tier matches are recorded on the dashboard but send no message, "
            "per the four-tier alert table."
        ),
    }, case, response)


@router.get("/{rule_id}/alerts")
def rule_alerts(
    rule_id: str,
    response: Response,
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    rule = db.get(CustomAlertRule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    # Two ways an alert relates to a rule: the rule raised it, or the rule matched
    # an alert that was already open on that slope. Both belong in this list, or the
    # rules page tells an operator their rule has never fired when it fires hourly.
    matched_ids = {
        e.alert_id for e in db.scalars(
            select(AlertEvent).where(
                AlertEvent.event == "CUSTOM_RULE_MATCHED",
                AlertEvent.detail.like(f"{rule_id}:%"),
            )
        ).all()
    }
    q = select(Alert).where(
        or_(Alert.custom_rule_id == rule_id, Alert.id.in_(matched_ids or {"__none__"}))
    )
    if active_only:
        q = q.where(Alert.status != "RESOLVED")
    rows = db.scalars(q.order_by(Alert.issued_at.desc())).all()

    payload = []
    for a in rows:
        item = S.alert(a)
        item["relation"] = "RAISED" if a.custom_rule_id == rule_id else "MATCHED_OPEN_ALERT"
        payload.append(item)
    return respond(payload, case, response)


@router.post("/evaluate")
def evaluate_now(
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    """Run a full cycle immediately so a newly saved rule is tested at once."""
    result = services.run_risk_cycle(db, send=True)
    return respond({"ran_at": utcnow().isoformat(), **result}, case, response)
