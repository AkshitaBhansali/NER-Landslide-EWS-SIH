"""ORM models.

Column names are snake_case and match the payload contract exactly, so the
serialisers are mostly a straight dump. Anything the frontend reads as camelCase is
handled once, in app/casing.py, not per-model.

Geometry is stored as GeoJSON in JSON columns. That keeps SQLite viable for the
prototype; moving to PostGIS means changing these four columns to `Geometry` and
nothing else.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------- #
# Reference geography
# --------------------------------------------------------------------------- #
class District(Base):
    __tablename__ = "districts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    state_code: Mapped[str] = mapped_column(String(4), index=True, nullable=False)
    state_name: Mapped[str] = mapped_column(String(80), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    population: Mapped[int] = mapped_column(Integer, default=0)
    terrain: Mapped[str] = mapped_column(String(24), default="HILL")
    # District-specific 24h rainfall threshold. Seeded from terrain, overridable per district.
    alert_threshold_24h: Mapped[float] = mapped_column(Float, default=95.0)

    zones: Mapped[list["RiskZone"]] = relationship(back_populates="district_ref")


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #
class RiskZone(Base, TimestampMixin):
    """A scored slope unit. One district has 1-3 of these."""

    __tablename__ = "risk_zones"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    district_id: Mapped[str] = mapped_column(ForeignKey("districts.id"), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)

    # --- static terrain factors (LSI inputs) ---
    slope_deg: Mapped[float] = mapped_column(Float, default=0)
    elevation_m: Mapped[float] = mapped_column(Float, default=0)
    aspect_deg: Mapped[float] = mapped_column(Float, default=0)
    soil_type: Mapped[str] = mapped_column(String(32), default="Silty Loam")
    landcover: Mapped[str] = mapped_column(String(32), default="Plantation")

    # --- dynamic trigger factors (TI inputs) ---
    rainfall_24h_mm: Mapped[float] = mapped_column(Float, default=0)
    rainfall_72h_mm: Mapped[float] = mapped_column(Float, default=0)
    rainfall_7d_mm: Mapped[float] = mapped_column(Float, default=0)
    antecedent_precip_index: Mapped[float] = mapped_column(Float, default=0)
    soil_moisture_pct: Mapped[float] = mapped_column(Float, default=0)

    # --- model output ---
    lsi: Mapped[float] = mapped_column(Float, default=0)
    ti: Mapped[float] = mapped_column(Float, default=0)
    risk_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    alert_tier: Mapped[str] = mapped_column(String(8), default="GREEN")
    probability: Mapped[float] = mapped_column(Float, default=0)
    contributing_factors: Mapped[dict] = mapped_column(JSON, default=dict)
    sensor_confidence: Mapped[float] = mapped_column(Float, default=100)
    expected_window_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    population: Mapped[int] = mapped_column(Integer, default=0)
    geometry: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(24), default="RULE_ENGINE")  # or ML_MODEL
    model_version: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # The classifier's probability, recorded on every cycle even when the rule
    # engine's score is the one published. Keeping both is what lets the console
    # show that the statistical and mechanical views disagreed — which is itself a
    # signal, and is lost if only the winning number is stored.
    model_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Set only by POST /api/model/predict — an external pipeline deliberately
    # publishing a score. In-process inference does NOT set it. The distinction
    # matters: a deliberate publish is authoritative for a window and must survive
    # later cycles, whereas in-process inference is just this cycle's opinion and
    # is recomputed every time.
    model_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data_confidence: Mapped[str] = mapped_column(String(16), default="SYNTHETIC")

    district_ref: Mapped[District] = relationship(back_populates="zones")
    sensors: Mapped[list["Sensor"]] = relationship(back_populates="zone")


class RiskHistory(Base):
    """Append-only score history. Feeds /risk/trend and the quarterly report."""

    __tablename__ = "risk_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("risk_zones.id"), index=True)
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16))
    rainfall_24h_mm: Mapped[float] = mapped_column(Float, default=0)
    soil_moisture_pct: Mapped[float] = mapped_column(Float, default=0)


# --------------------------------------------------------------------------- #
# Sensors
# --------------------------------------------------------------------------- #
class Sensor(Base, TimestampMixin):
    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    zone_id: Mapped[str] = mapped_column(ForeignKey("risk_zones.id"), index=True)
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    sensor_type: Mapped[str] = mapped_column(String(32), index=True)
    unit: Mapped[str] = mapped_column(String(16))
    reading: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ONLINE", index=True)
    health_score: Mapped[float] = mapped_column(Float, default=100)
    health_sub_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    battery_pct: Mapped[float] = mapped_column(Float, default=100)
    rssi_dbm: Mapped[float] = mapped_column(Float, default=-70)
    expected_interval_s: Mapped[int] = mapped_column(Integer, default=900)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    risk_contribution: Mapped[float] = mapped_column(Float, default=0)
    maintenance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    transport: Mapped[str] = mapped_column(String(16), default="LORAWAN")  # LORAWAN|GSM|SATELLITE

    zone: Mapped[RiskZone] = relationship(back_populates="sensors")


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_reading_sensor_time", "sensor_id", "timestamp"),
        # Idempotency for store-and-forward replays from a gateway.
        UniqueConstraint("sensor_id", "timestamp", name="uq_reading_sensor_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(ForeignKey("sensors.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    quality_flag: Mapped[str] = mapped_column(String(16), default="OK")  # OK|SUSPECT|REJECTED
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    tier: Mapped[str] = mapped_column(String(8), default="YELLOW")
    title: Mapped[str] = mapped_column(String(200))
    zone_id: Mapped[str] = mapped_column(ForeignKey("risk_zones.id"), index=True)
    location: Mapped[str] = mapped_column(String(200))
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    risk_score: Mapped[float] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float)
    trigger: Mapped[str] = mapped_column(String(32), index=True)
    trigger_detail: Mapped[str] = mapped_column(Text, default="")
    rule_id: Mapped[str] = mapped_column(String(32), default="")
    # HAZARD ("the slope may fail") vs OPERATIONAL ("we can no longer tell").
    # Persisted rather than derived from `trigger`, because a custom rule's class
    # depends on the parameters it was written against, not on its trigger label.
    alert_class: Mapped[str] = mapped_column(String(16), default="HAZARD", index=True)
    custom_rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Every rule that matched this zone on the latest cycle, not just the one that
    # won primacy. One hillside gets one alert, but an operator asking "why" needs
    # the full set: "R2 primary, and R6 says the road below is already blocked".
    contributing_rules: Mapped[list] = mapped_column(JSON, default=list)
    expected_window_hours: Mapped[int] = mapped_column(Integer, default=24)
    affected_roads: Mapped[list] = mapped_column(JSON, default=list)
    affected_villages: Mapped[list] = mapped_column(JSON, default=list)
    population_affected: Mapped[int] = mapped_column(Integer, default=0)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sensor_confidence: Mapped[float] = mapped_column(Float, default=100)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_count: Mapped[int] = mapped_column(Integer, default=0)


class CustomAlertRule(Base, TimestampMixin):
    """An operator-defined threshold rule, evaluated by the backend on every cycle.

    These sit alongside R1-R7 rather than replacing them. The built-in rules encode
    the failure physics; a custom rule encodes local knowledge — "this cutting goes
    at 90 mm, not 150" — which only the district office has. Evaluation happens
    server-side for the same reason the built-in rules do: a threshold that only
    exists in a browser tab stops existing when the tab is closed.
    """

    __tablename__ = "custom_alert_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")

    # Where it applies. ALL | STATE | DISTRICT | ZONE
    scope_type: Mapped[str] = mapped_column(String(16), default="ALL", index=True)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # [{parameter, operator, value, value2?}] combined by `match`.
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    match: Mapped[str] = mapped_column(String(8), default="ALL")     # ALL | ANY

    # AUTO maps the zone score through the NDMA/GSI tier table in the methodology note.
    severity: Mapped[str] = mapped_column(String(16), default="AUTO")
    alert_class: Mapped[str] = mapped_column(String(16), default="AUTO")  # HAZARD|OPERATIONAL|AUTO

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=45)

    created_by: Mapped[str] = mapped_column(String(120), default="operator")
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    matching_zones: Mapped[list] = mapped_column(JSON, default=list)


class AlertEvent(Base):
    """Audit trail. Every transition is written here; nothing mutates silently."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(120), default="system")
    detail: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #
class Recipient(Base):
    """Who gets told. Audience is how the tier table routes messages."""

    __tablename__ = "recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(48))  # DM | SDRF | WARD_MEMBER | PUBLIC | ...
    audience: Mapped[str] = mapped_column(String(24), index=True)  # AUTHORITY|LOCAL|PUBLIC
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    msisdn: Mapped[str] = mapped_column(String(24))
    language: Mapped[str] = mapped_column(String(8), default="en")
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["SMS", "PUSH"])
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Dispatch(Base):
    """One row per message attempt. This is the delivery ledger."""

    __tablename__ = "dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("recipients.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    audience: Mapped[str] = mapped_column(String(24))
    msisdn: Mapped[str] = mapped_column(String(24), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# Infrastructure and connectivity
# --------------------------------------------------------------------------- #
class Road(Base, TimestampMixin):
    __tablename__ = "roads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    length_km: Mapped[float] = mapped_column(Float, default=0)
    path: Mapped[list] = mapped_column(JSON, default=list)  # [[lng,lat], ...]
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Village(Base):
    __tablename__ = "villages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    population: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    connectivity: Mapped[str] = mapped_column(String(16), default="CONNECTED")


class Infrastructure(Base):
    __tablename__ = "infrastructure"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    infra_type: Mapped[str] = mapped_column(String(24), index=True)
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    importance: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    exposure: Mapped[str] = mapped_column(String(16), default="LOW")
    population_served: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- #
# Incidents and field reports
# --------------------------------------------------------------------------- #
class HistoricalIncident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    location: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    incident_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    rainfall_24h_mm: Mapped[float] = mapped_column(Float, default=0)
    risk_score_at_event: Mapped[float] = mapped_column(Float, default=0)
    affected_road: Mapped[str] = mapped_column(String(160), default="")
    affected_population: Mapped[int] = mapped_column(Integer, default=0)
    response_time_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="CLOSED")
    predicted: Mapped[bool] = mapped_column(Boolean, default=False)
    data_confidence: Mapped[str] = mapped_column(String(16), default="SYNTHETIC")


class IncidentReport(Base, TimestampMixin):
    """Citizen / field officer submission. Treated as a signal, never as ground truth."""

    __tablename__ = "field_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Client-generated key. Makes offline replay idempotent.
    client_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    incident_type: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    state_code: Mapped[str] = mapped_column(String(4), index=True)
    road_or_village: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="MODERATE", index=True)
    reporter_type: Mapped[str] = mapped_column(String(24), default="CITIZEN")
    reporter_name: Mapped[str] = mapped_column(String(120), default="Anonymous")
    reporter_contact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(16), default="SYNCED", index=True)
    verification: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReportMedia(Base):
    __tablename__ = "field_report_media"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("field_reports.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="IMAGE")  # IMAGE | VIDEO
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #
class WeatherObservation(Base):
    __tablename__ = "weather"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str] = mapped_column(String(120))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    rainfall_now_mm: Mapped[float] = mapped_column(Float, default=0)
    rainfall_24h_mm: Mapped[float] = mapped_column(Float, default=0)
    rainfall_72h_mm: Mapped[float] = mapped_column(Float, default=0)
    rainfall_7d_mm: Mapped[float] = mapped_column(Float, default=0)
    humidity_pct: Mapped[float] = mapped_column(Float, default=0)
    temperature_c: Mapped[float] = mapped_column(Float, default=0)
    wind_kph: Mapped[float] = mapped_column(Float, default=0)
    condition: Mapped[str] = mapped_column(String(24), default="CLEAR")
    weather_risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    alert_threshold_24h: Mapped[float] = mapped_column(Float, default=95)
    forecast: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32), default="IMD_PLACEHOLDER")


# --------------------------------------------------------------------------- #
# Platform
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default="VIEWER")
    district_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    href: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class ModelRun(Base):
    """Registry of ML training runs. Lets the console report a real model version."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(48), index=True)
    algorithm: Mapped[str] = mapped_column(String(48), default="RandomForest")
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    zones_scored: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_importance: Mapped[list] = mapped_column(JSON, default=list)
    evaluated_on: Mapped[str] = mapped_column(Text, default="")
    caveat: Mapped[str] = mapped_column(Text, default="")


class SyncLedger(Base):
    """Idempotency record for offline batch sync. One row per accepted client operation."""

    __tablename__ = "sync_ledger"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    op: Mapped[str] = mapped_column(String(32))
    server_id: Mapped[str] = mapped_column(String(48))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobRecord(Base):
    """Async job handle for report generation."""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    scope_id: Mapped[str] = mapped_column(String(64), default="ALL")
    fmt: Mapped[str] = mapped_column(String(8), default="pdf")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
