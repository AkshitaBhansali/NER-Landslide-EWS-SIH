"""Custom alert rules.

A district office knows things the model does not. The cutting at Mahur fails at
90 mm of rain, not the 150 mm regional critical threshold; the slope above the
Zubza school has moved twice this decade. This module lets that knowledge become a
rule the engine evaluates, instead of a note in somebody's diary.

Design constraints, in the order they mattered:

1. **Server-side evaluation.** A rule that lives in React state is gone when the
   tab closes and never fires at 03:00 when the duty officer is asleep. Rules are
   rows; they are evaluated inside `run_risk_cycle` alongside R1-R7.

2. **The parameter vocabulary is the methodology note's vocabulary.** Every
   parameter below is a variable the note defines — the LSI inputs (slope, soil,
   landcover, elevation, aspect), the TI inputs (24h/72h/7d rainfall, API, soil
   moisture), the composite outputs (LSI, TI, risk score, probability) — plus the
   sensor-confidence terms the platform adds. Operators cannot invent a variable
   the risk engine has never heard of, which is what keeps a custom rule
   explainable after it fires.

3. **Severity defaults to the note's tier table.** With `severity = "AUTO"` the
   final score is mapped through the NDMA/GSI table exactly as specified:

       0.00-0.40  GREEN   no warning        -> INFORMATION, no dispatch
       0.41-0.65  YELLOW  watch             -> MODERATE, authorities only
       0.66-0.85  ORANGE  alert             -> HIGH, authorities + ward members
       0.86-1.00  RED     action            -> CRITICAL, public broadcast

   An operator may pin a severity instead, but the tier — and therefore the
   audience — is always derived from the score, so no custom rule can quietly
   trigger a public SMS on a score the note says is a Green day.

4. **HAZARD and OPERATIONAL stay separate.** A rule written on sensor health is an
   operational alert. It must never dedupe against, or overwrite, a hazard alert on
   the same slope. The class is inferred from the parameters used unless pinned.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CustomAlertRule, RiskZone, Sensor, SensorReading, utcnow
from .alert_engine import Candidate

# --------------------------------------------------------------------------- #
# Parameter catalogue
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    unit: str
    kind: str                # NUMBER | LEVEL | TEXT
    group: str               # HAZARD | OPERATIONAL
    hint: str
    choices: tuple[str, ...] = ()


PARAMETERS: tuple[Parameter, ...] = (
    # --- composite risk outputs -------------------------------------------
    Parameter("risk_score", "Risk score", "0-100", "NUMBER", "HAZARD",
              "Final score: (LSI x 0.4 + TI x 0.6) x 100"),
    Parameter("risk_level", "Risk level", "", "LEVEL", "HAZARD",
              "Display band of the risk score",
              ("LOW", "MODERATE", "HIGH", "CRITICAL")),
    Parameter("probability", "Failure probability", "0-1", "NUMBER", "HAZARD",
              "Calibrated probability from the composite score"),
    Parameter("lsi", "Susceptibility index (LSI)", "0-1", "NUMBER", "HAZARD",
              "Static terrain susceptibility"),
    Parameter("ti", "Triggering index (TI)", "0-1", "NUMBER", "HAZARD",
              "Dynamic rainfall and moisture trigger"),
    # --- TI inputs ---------------------------------------------------------
    Parameter("rainfall_24h_mm", "Rainfall 24h", "mm", "NUMBER", "HAZARD",
              "Regional critical threshold 150 mm"),
    Parameter("rainfall_72h_mm", "Rainfall 72h", "mm", "NUMBER", "HAZARD",
              "Regional critical threshold 250 mm"),
    Parameter("rainfall_7d_mm", "Rainfall 7d", "mm", "NUMBER", "HAZARD",
              "Regional critical threshold 400 mm"),
    Parameter("antecedent_precip_index", "Antecedent precipitation index", "", "NUMBER", "HAZARD",
              "API_t = P_t + 0.85 x API_(t-1); gauge-only proxy for soil wetness"),
    Parameter("soil_moisture_pct", "Soil moisture", "% VWC", "NUMBER", "HAZARD",
              "Above 70% the triggering threshold drops sharply"),
    # --- LSI inputs --------------------------------------------------------
    Parameter("slope_deg", "Slope", "deg", "NUMBER", "HAZARD",
              "30-45 deg is the critical failure window for soil slopes"),
    Parameter("elevation_m", "Elevation", "m", "NUMBER", "HAZARD",
              "500-1500 m carries the thickest colluvium"),
    Parameter("aspect_deg", "Aspect", "deg", "NUMBER", "HAZARD",
              "225 deg (SW) faces the monsoon directly"),
    Parameter("soil_type", "Soil type", "", "TEXT", "HAZARD",
              "Clayey and expansive soils lose shear strength when wet",
              ("Bedrock", "Gravel", "Sand", "Silty Loam", "Laterite", "Clayey")),
    Parameter("landcover", "Landcover", "", "TEXT", "HAZARD",
              "Barren, deforested and cut slopes have no root cohesion",
              ("Dense Forest", "Plantation", "Agriculture", "Built-up", "Barren", "Cut Slope")),
    # --- movement ----------------------------------------------------------
    Parameter("slope_movement", "Slope movement", "deg / mm", "NUMBER", "HAZARD",
              "Largest tiltmeter or extensometer change over the last four readings"),
    # --- operational -------------------------------------------------------
    Parameter("sensor_confidence", "Sensor confidence", "0-100", "OPERATIONAL_NUMBER",
              "OPERATIONAL", "Zone confidence from sensor health and coverage"),
    Parameter("min_sensor_health", "Worst sensor health", "0-100", "OPERATIONAL_NUMBER",
              "OPERATIONAL", "Lowest health score among the zone's sensors"),
    Parameter("sensors_offline_pct", "Sensors offline", "%", "OPERATIONAL_NUMBER",
              "OPERATIONAL", "Share of the zone's fleet that is offline"),
    Parameter("min_battery_pct", "Lowest battery", "%", "OPERATIONAL_NUMBER",
              "OPERATIONAL", "Lowest battery level among the zone's sensors"),
)

PARAM_BY_KEY = {p.key: p for p in PARAMETERS}

OPERATORS = {
    "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<=",
    "EQ": "=", "NEQ": "!=", "BETWEEN": "between", "IN": "is one of",
}

LEVEL_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}

# The methodology note's tier table, on the 0-100 scale the platform uses.
DOC_TIERS = (
    (86.0, "RED", "CRITICAL", "Action \u2014 critical danger, imminent slope failure."),
    (66.0, "ORANGE", "HIGH", "Alert \u2014 threshold crossed, high probability of slope failure."),
    (41.0, "YELLOW", "MODERATE", "Watch \u2014 soil saturated, landslides possible if rain continues."),
    (0.0, "GREEN", "INFORMATION", "No warning \u2014 normal conditions."),
)


def tier_for(score: float) -> tuple[str, str, str]:
    """(tier, severity, status) straight from the note's four-tier table."""
    for floor, tier, severity, status in DOC_TIERS:
        if score >= floor:
            return tier, severity, status
    return "GREEN", "INFORMATION", DOC_TIERS[-1][3]


# --------------------------------------------------------------------------- #
# Zone facts
# --------------------------------------------------------------------------- #
def zone_facts(db: Session, zone: RiskZone) -> dict:
    """Every parameter's current value for one zone, in one place.

    Built once per zone per cycle and shared across all rules — evaluating twenty
    rules must not mean twenty passes over the sensor tables.
    """
    facts: dict = {
        "risk_score": zone.risk_score,
        "risk_level": zone.risk_level,
        "probability": zone.probability,
        "lsi": zone.lsi,
        "ti": zone.ti,
        "rainfall_24h_mm": zone.rainfall_24h_mm,
        "rainfall_72h_mm": zone.rainfall_72h_mm,
        "rainfall_7d_mm": zone.rainfall_7d_mm,
        "antecedent_precip_index": zone.antecedent_precip_index,
        "soil_moisture_pct": zone.soil_moisture_pct,
        "slope_deg": zone.slope_deg,
        "elevation_m": zone.elevation_m,
        "aspect_deg": zone.aspect_deg,
        "soil_type": zone.soil_type,
        "landcover": zone.landcover,
        "sensor_confidence": zone.sensor_confidence,
    }

    sensors = db.scalars(select(Sensor).where(Sensor.zone_id == zone.id)).all()
    if sensors:
        facts["min_sensor_health"] = min(s.health_score for s in sensors)
        facts["min_battery_pct"] = min(s.battery_pct for s in sensors)
        offline = sum(1 for s in sensors if s.status == "OFFLINE")
        facts["sensors_offline_pct"] = round(offline / len(sensors) * 100, 1)
    else:
        facts["min_sensor_health"] = 0.0
        facts["min_battery_pct"] = 0.0
        facts["sensors_offline_pct"] = 100.0

    movement = 0.0
    for s in sensors:
        if s.sensor_type not in ("TILTMETER", "EXTENSOMETER") or s.status == "OFFLINE":
            continue
        rows = db.scalars(
            select(SensorReading)
            .where(SensorReading.sensor_id == s.id)
            .order_by(SensorReading.timestamp.desc())
            .limit(4)
        ).all()
        if len(rows) >= 2:
            vals = [r.value for r in reversed(rows)]
            movement = max(movement, abs(vals[-1] - vals[0]))
    facts["slope_movement"] = round(movement, 3)
    return facts


# --------------------------------------------------------------------------- #
# Condition evaluation
# --------------------------------------------------------------------------- #
def _as_number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(cond: dict, facts: dict) -> tuple[bool, str]:
    """Returns (matched, human-readable evidence)."""
    key = cond.get("parameter")
    op = (cond.get("operator") or "GTE").upper()
    param = PARAM_BY_KEY.get(key)
    if param is None or key not in facts:
        return False, f"unknown parameter {key}"

    actual = facts[key]
    unit = f" {param.unit}" if param.unit and param.unit not in ("", "0-1", "0-100") else ""

    # Risk levels compare by rank, not alphabetically: HIGH > MODERATE.
    if param.kind == "LEVEL":
        want = str(cond.get("value", "")).upper()
        a, b = LEVEL_RANK.get(str(actual).upper(), -1), LEVEL_RANK.get(want, -1)
        matched = {
            "GTE": a >= b, "GT": a > b, "LTE": a <= b, "LT": a < b,
            "EQ": a == b, "NEQ": a != b,
        }.get(op, a >= b)
        return matched, f"{param.label} is {actual} ({OPERATORS.get(op, op)} {want})"

    if param.kind == "TEXT":
        want = cond.get("value")
        values = [str(v).strip().upper() for v in (want if isinstance(want, list) else [want])]
        actual_s = str(actual).strip().upper()
        matched = actual_s in values if op in ("IN", "EQ") else actual_s not in values
        return matched, f"{param.label} is {actual}"

    a = _as_number(actual)
    if a is None:
        return False, f"{param.label} unavailable"

    if op == "BETWEEN":
        lo, hi = _as_number(cond.get("value")), _as_number(cond.get("value2"))
        if lo is None or hi is None:
            return False, f"{param.label}: incomplete range"
        return lo <= a <= hi, f"{param.label} {a:g}{unit} (between {lo:g} and {hi:g})"

    b = _as_number(cond.get("value"))
    if b is None:
        return False, f"{param.label}: no threshold set"
    matched = {
        "GT": a > b, "GTE": a >= b, "LT": a < b, "LTE": a <= b,
        "EQ": a == b, "NEQ": a != b,
    }.get(op, a >= b)
    return matched, f"{param.label} {a:g}{unit} {OPERATORS.get(op, op)} {b:g}{unit}"


def rule_applies_to(rule: CustomAlertRule, zone: RiskZone) -> bool:
    scope = (rule.scope_type or "ALL").upper()
    if scope == "ALL" or not rule.scope_id or rule.scope_id == "ALL":
        return True
    if scope == "STATE":
        return zone.state_code == rule.scope_id
    if scope == "DISTRICT":
        return zone.district_id == rule.scope_id
    if scope == "ZONE":
        return zone.id == rule.scope_id
    return False


def infer_class(rule: CustomAlertRule) -> str:
    """Sensor-derived rules are operational; everything else is a hazard."""
    if (rule.alert_class or "AUTO").upper() in ("HAZARD", "OPERATIONAL"):
        return rule.alert_class.upper()
    groups = {
        PARAM_BY_KEY[c["parameter"]].group
        for c in (rule.conditions or [])
        if c.get("parameter") in PARAM_BY_KEY
    }
    return "OPERATIONAL" if groups == {"OPERATIONAL"} else "HAZARD"


def _in_cooldown(rule: CustomAlertRule) -> bool:
    if not rule.last_triggered_at:
        return False
    last = rule.last_triggered_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    # `or` would be wrong here: a rule with cooldown 0 means "no cooldown", and
    # 0 is falsy, so it would silently inherit the 45-minute default.
    minutes = (rule.cooldown_minutes if rule.cooldown_minutes is not None
               else settings.custom_rule_cooldown_minutes)
    if minutes <= 0:
        return False
    window = timedelta(minutes=minutes)
    return utcnow() - last < window


def evaluate_rule(rule: CustomAlertRule, zone: RiskZone, facts: dict) -> tuple[bool, list[str]]:
    conds = rule.conditions or []
    if not conds:
        return False, []
    results = [evaluate_condition(c, facts) for c in conds]
    matched = [ev for ok, ev in results if ok]
    if (rule.match or "ALL").upper() == "ANY":
        return bool(matched), matched
    return all(ok for ok, _ in results), [ev for _, ev in results]


def evaluate_zone(db: Session, zone: RiskZone,
                  rules: list[CustomAlertRule] | None = None) -> list[Candidate]:
    """Candidates from every enabled custom rule that matches this zone."""
    if rules is None:
        rules = db.scalars(
            select(CustomAlertRule).where(CustomAlertRule.enabled.is_(True))
        ).all()
    if not rules:
        return []

    facts = zone_facts(db, zone)
    out: list[Candidate] = []
    for rule in rules:
        if not rule_applies_to(rule, zone):
            continue
        matched, evidence = evaluate_rule(rule, zone, facts)
        if not matched or _in_cooldown(rule):
            continue

        tier, auto_severity, status = tier_for(zone.risk_score)
        severity = auto_severity if (rule.severity or "AUTO").upper() == "AUTO" \
            else rule.severity.upper()
        out.append(Candidate(
            zone_id=zone.id,
            rule_id=rule.id,
            trigger="CUSTOM_RULE",
            severity=severity,
            detail=f"{rule.name}: " + "; ".join(evidence[:3]),
            score=zone.risk_score,
            meta={
                "custom_rule_id": rule.id,
                "custom_rule_name": rule.name,
                "alert_class": infer_class(rule),
                "tier": tier,
                "tier_status": status,
                "notify": bool(rule.notify),
                "evidence": evidence,
            },
        ))
    return out


def record_fire(rule: CustomAlertRule, zone_ids: list[str]) -> None:
    rule.last_triggered_at = utcnow()
    rule.trigger_count = (rule.trigger_count or 0) + 1
    rule.matching_zones = zone_ids


def catalogue() -> dict:
    """Everything the rule builder UI needs, sourced from one place."""
    return {
        "parameters": [
            {
                "key": p.key, "label": p.label, "unit": p.unit,
                "kind": "NUMBER" if p.kind.endswith("NUMBER") else p.kind,
                "group": p.group, "hint": p.hint, "choices": list(p.choices),
            }
            for p in PARAMETERS
        ],
        "operators": [{"key": k, "label": v} for k, v in OPERATORS.items()],
        "severities": ["AUTO", "INFORMATION", "MODERATE", "HIGH", "CRITICAL"],
        "scopes": ["ALL", "STATE", "DISTRICT", "ZONE"],
        "match_modes": ["ALL", "ANY"],
        "tier_table": [
            {"from": 0, "to": 40, "tier": "GREEN", "severity": "INFORMATION",
             "status": DOC_TIERS[3][3], "audience": "No message sent"},
            {"from": 41, "to": 65, "tier": "YELLOW", "severity": "MODERATE",
             "status": DOC_TIERS[2][3], "audience": "District Magistrate, SDRF"},
            {"from": 66, "to": 85, "tier": "ORANGE", "severity": "HIGH",
             "status": DOC_TIERS[1][3], "audience": "Authorities and local ward members"},
            {"from": 86, "to": 100, "tier": "RED", "severity": "CRITICAL",
             "status": DOC_TIERS[0][3], "audience": "General public, geo-fenced broadcast"},
        ],
    }
