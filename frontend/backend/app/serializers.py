"""ORM -> wire contract.

One function per DTO, all snake_case. Nested `location`/`center` objects are kept as
`{lat, lng}` because that is what the frontend's projection layer consumes; storing
them as flat columns and assembling here means we can move to PostGIS geometry
without changing a single response shape.
"""
from __future__ import annotations

from datetime import datetime

from .models import (
    Alert,
    AlertEvent,
    Dispatch,
    HistoricalIncident,
    IncidentReport,
    Infrastructure,
    ModelRun,
    Notification,
    Recipient,
    ReportMedia,
    RiskZone,
    Road,
    Sensor,
    SensorReading,
    Village,
    WeatherObservation,
)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def risk_zone(z: RiskZone) -> dict:
    return {
        "id": z.id,
        "name": z.name,
        "district": z.district,
        "district_id": z.district_id,
        "state_code": z.state_code,
        "center": {"lat": z.lat, "lng": z.lng},
        "risk_score": z.risk_score,
        "risk_level": z.risk_level,
        "alert_tier": z.alert_tier,
        "probability": z.probability,
        "lsi": z.lsi,
        "ti": z.ti,
        "rainfall_24h_mm": z.rainfall_24h_mm,
        "rainfall_72h_mm": z.rainfall_72h_mm,
        "rainfall_7d_mm": z.rainfall_7d_mm,
        "antecedent_precip_index": z.antecedent_precip_index,
        "soil_moisture_pct": z.soil_moisture_pct,
        "slope_deg": z.slope_deg,
        "elevation_m": z.elevation_m,
        "aspect_deg": z.aspect_deg,
        "soil_type": z.soil_type,
        "landcover": z.landcover,
        "sensor_confidence": z.sensor_confidence,
        "contributing_factors": z.contributing_factors,
        "population": z.population,
        "recommended_action": z.recommended_action,
        "expected_window_hours": z.expected_window_hours,
        "geometry": z.geometry,
        "source": z.source,
        "model_version": z.model_version,
        "model_probability": z.model_probability,
        "updated_at": iso(z.updated_at),
        "data_confidence": z.data_confidence,
    }


def sensor(s: Sensor) -> dict:
    return {
        "sensor_id": s.id,
        "id": s.id,
        "name": s.name,
        "zone_id": s.zone_id,
        "district": s.district,
        "district_id": s.district_id,
        "state_code": s.state_code,
        "location": {"lat": s.lat, "lng": s.lng},
        "sensor_type": s.sensor_type,
        "reading": s.reading,
        "unit": s.unit,
        "status": s.status,
        "health_score": s.health_score,
        "health_sub_scores": s.health_sub_scores,
        "battery_pct": s.battery_pct,
        "rssi_dbm": s.rssi_dbm,
        "expected_interval_s": s.expected_interval_s,
        "last_seen": iso(s.last_seen),
        "risk_contribution": s.risk_contribution,
        "maintenance_note": s.maintenance_note,
        "installed_on": iso(s.installed_on),
        "transport": s.transport,
    }


def sensor_reading(r: SensorReading) -> dict:
    return {
        "sensor_id": r.sensor_id,
        "timestamp": iso(r.timestamp),
        "value": r.value,
        "unit": r.unit,
        "quality_flag": r.quality_flag,
    }


def alert(a: Alert) -> dict:
    return {
        "id": a.id,
        "severity": a.severity,
        "tier": a.tier,
        "title": a.title,
        "zone_id": a.zone_id,
        "location": a.location,
        "district": a.district,
        "district_id": a.district_id,
        "state_code": a.state_code,
        "center": {"lat": a.lat, "lng": a.lng},
        "issued_at": iso(a.issued_at),
        "risk_score": a.risk_score,
        "probability": a.probability,
        "trigger": a.trigger,
        "trigger_detail": a.trigger_detail,
        "rule_id": a.rule_id,
        "alert_class": a.alert_class or "HAZARD",
        "custom_rule_id": a.custom_rule_id,
        "contributing_rules": a.contributing_rules or [],
        "expected_window_hours": a.expected_window_hours,
        "affected_roads": a.affected_roads,
        "affected_villages": a.affected_villages,
        "population_affected": a.population_affected,
        "recommended_action": a.recommended_action,
        "status": a.status,
        "acknowledged_by": a.acknowledged_by,
        "acknowledged_at": iso(a.acknowledged_at),
        "dispatched_at": iso(a.dispatched_at),
        "resolved_at": iso(a.resolved_at),
        "sensor_confidence": a.sensor_confidence,
        "low_confidence": a.low_confidence,
        "escalation_count": a.escalation_count,
    }


def alert_event(e: AlertEvent) -> dict:
    return {"at": iso(e.at), "event": e.event, "actor": e.actor, "detail": e.detail}


def dispatch(d: Dispatch) -> dict:
    return {
        "id": d.id,
        "alert_id": d.alert_id,
        "channel": d.channel,
        "audience": d.audience,
        "msisdn": d.msisdn[:-4] + "****" if len(d.msisdn) > 4 else d.msisdn,
        "language": d.language,
        "body": d.body,
        "status": d.status,
        "attempts": d.attempts,
        "last_error": d.last_error,
        "queued_at": iso(d.queued_at),
        "sent_at": iso(d.sent_at),
    }


def road(r: Road) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "district_id": r.district_id,
        "district": r.district,
        "state_code": r.state_code,
        "status": r.status,
        "risk_level": r.risk_level,
        "length_km": r.length_km,
        "path": r.path,
        "note": r.note,
        "last_updated": iso(r.last_updated),
    }


def village(v: Village) -> dict:
    return {
        "id": v.id,
        "name": v.name,
        "district_id": v.district_id,
        "district": v.district,
        "state_code": v.state_code,
        "location": {"lat": v.lat, "lng": v.lng},
        "population": v.population,
        "risk_level": v.risk_level,
        "connectivity": v.connectivity,
    }


def infrastructure(i: Infrastructure) -> dict:
    return {
        "id": i.id,
        "name": i.name,
        "type": i.infra_type,
        "district_id": i.district_id,
        "district": i.district,
        "state_code": i.state_code,
        "location": {"lat": i.lat, "lng": i.lng},
        "risk_level": i.risk_level,
        "importance": i.importance,
        "exposure": i.exposure,
        "population_served": i.population_served,
    }


def incident(i: HistoricalIncident) -> dict:
    return {
        "id": i.id,
        "date": iso(i.date),
        "district": i.district,
        "district_id": i.district_id,
        "state_code": i.state_code,
        "location": i.location,
        "center": {"lat": i.lat, "lng": i.lng},
        "incident_type": i.incident_type,
        "severity": i.severity,
        "rainfall_24h_mm": i.rainfall_24h_mm,
        "risk_score_at_event": i.risk_score_at_event,
        "affected_road": i.affected_road,
        "affected_population": i.affected_population,
        "response_time_minutes": i.response_time_minutes,
        "status": i.status,
        "predicted": i.predicted,
        "data_confidence": i.data_confidence,
    }


def media(m: ReportMedia) -> dict:
    return {
        "id": m.id,
        "kind": m.kind,
        "filename": m.filename,
        "content_type": m.content_type,
        "size_bytes": m.size_bytes,
        "url": m.url,
        "uploaded_at": iso(m.uploaded_at),
    }


def field_report(r: IncidentReport, attachments: list[ReportMedia] | None = None) -> dict:
    return {
        "id": r.id,
        "client_id": r.client_id,
        "incident_type": r.incident_type,
        "description": r.description,
        "district": r.district,
        "district_id": r.district_id,
        "state_code": r.state_code,
        "road_or_village": r.road_or_village,
        "location": {"lat": r.lat, "lng": r.lng},
        "gps_accuracy_m": r.gps_accuracy_m,
        "severity": r.severity,
        "reporter_type": r.reporter_type,
        "reporter_name": r.reporter_name,
        "reported_at": iso(r.reported_at),
        "captured_at": iso(r.captured_at),
        "media": [media(m) for m in (attachments or [])],
        "sync_status": r.sync_status,
        "verification": r.verification,
        "verified_by": r.verified_by,
        "verification_note": r.verification_note,
    }


def weather(w: WeatherObservation) -> dict:
    return {
        "district_id": w.district_id,
        "district": w.district,
        "observed_at": iso(w.observed_at),
        "rainfall_now": w.rainfall_now_mm,
        "rainfall_24h": w.rainfall_24h_mm,
        "rainfall_72h": w.rainfall_72h_mm,
        "rainfall_7d": w.rainfall_7d_mm,
        "humidity": w.humidity_pct,
        "temperature": w.temperature_c,
        "wind_kph": w.wind_kph,
        "condition": w.condition,
        "weather_risk_level": w.weather_risk_level,
        "alert_threshold_24h": w.alert_threshold_24h,
        "forecast": w.forecast,
        "source": w.source,
    }


def notification(n: Notification) -> dict:
    return {
        "id": n.id,
        "category": n.category,
        "title": n.title,
        "body": n.body,
        "created_at": iso(n.created_at),
        "read": n.read,
        "href": n.href,
        "district_id": n.district_id,
    }


def recipient(r: Recipient) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "role": r.role,
        "audience": r.audience,
        "district_id": r.district_id,
        "msisdn": r.msisdn[:-4] + "****",
        "language": r.language,
        "channels": r.channels,
        "active": r.active,
    }


def model_run(m: ModelRun) -> dict:
    return {
        "model_version": m.model_version,
        "algorithm": m.algorithm,
        "ran_at": iso(m.ran_at),
        "zones_scored": m.zones_scored,
        "selected_model": m.algorithm,
        **m.metrics,
        "metrics": m.metrics,
        "feature_importance": m.feature_importance,
        "evaluated_on": m.evaluated_on,
        "caveat": m.caveat,
    }


def custom_rule(r) -> dict:
    """An operator-authored threshold rule, with enough evaluation state attached
    that the rules table answers "is it working?" without a second request."""
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "scope_type": r.scope_type,
        "scope_id": r.scope_id,
        "conditions": r.conditions or [],
        "match": r.match,
        "severity": r.severity,
        "alert_class": r.alert_class,
        "enabled": r.enabled,
        "notify": r.notify,
        "cooldown_minutes": r.cooldown_minutes,
        "created_by": r.created_by,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "last_evaluated_at": iso(r.last_evaluated_at),
        "last_triggered_at": iso(r.last_triggered_at),
        "trigger_count": r.trigger_count,
        "matching_zones": r.matching_zones or [],
    }
