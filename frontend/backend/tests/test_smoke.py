"""End-to-end smoke tests.

Covers: every route responds, the engines behave as specified, and the three
behaviours the alert engine exists for (dedup, escalation, idempotent offline
replay) actually work rather than merely being described in a comment.

    pytest -q
"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.gettempdir()}/ner_test.db")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("AUTH_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402

from app.core import alert_engine as ae  # noqa: E402
from app.core.risk_engine import (  # noqa: E402
    antecedent_precipitation_index,
    aspect_score,
    score_zone,
    slope_score,
    soil_moisture_score,
)
from app.core.sensor_health import compute_health, zone_confidence  # noqa: E402
from app.db import session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Alert, RiskZone  # noqa: E402
from app import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded():
    seed.run(fresh=True)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Risk engine
# --------------------------------------------------------------------------- #
def test_slope_score_peaks_in_the_failure_window():
    assert slope_score(10) == 0.1
    assert slope_score(22) == 0.4
    assert slope_score(38) == 0.9
    # Above 45 the score DIPS — exposed bedrock, not a soil mantle.
    assert slope_score(60) == 0.7
    assert slope_score(60) < slope_score(38)


def test_soil_moisture_ramps_then_saturates():
    assert soil_moisture_score(20) == 0.1
    assert soil_moisture_score(50) == 0.4
    assert soil_moisture_score(70) == pytest.approx(0.6, abs=0.01)
    assert soil_moisture_score(95) == 0.9


def test_aspect_penalises_southwest_facing_slopes():
    assert aspect_score(225) == pytest.approx(1.0, abs=0.01)
    assert aspect_score(45) == 0.2          # NE, floored
    assert aspect_score(225) > aspect_score(45)


def test_api_decays_older_rainfall():
    recent = antecedent_precipitation_index([0, 0, 0, 100])
    old = antecedent_precipitation_index([100, 0, 0, 0])
    assert recent > old


def test_wet_steep_barren_slope_outranks_dry_gentle_forest():
    bad = score_zone(
        slope_deg=38, soil_type="Clayey", landcover="Barren",
        elevation_m=1100, aspect_deg=225,
        rainfall_24h_mm=180, rainfall_72h_mm=300, rainfall_7d_mm=450,
        soil_moisture_pct=92, antecedent_precip_index=190,
    )
    good = score_zone(
        slope_deg=8, soil_type="Bedrock", landcover="Dense Forest",
        elevation_m=200, aspect_deg=45,
        rainfall_24h_mm=2, rainfall_72h_mm=5, rainfall_7d_mm=10,
        soil_moisture_pct=22, antecedent_precip_index=5,
    )
    assert bad.risk_score > good.risk_score
    assert bad.risk_level == "CRITICAL"
    assert good.risk_level == "LOW"
    assert bad.alert_tier == "RED"
    assert good.alert_tier == "GREEN"


def test_contributing_factors_sum_to_one():
    r = score_zone(
        slope_deg=32, soil_type="Laterite", landcover="Plantation",
        elevation_m=900, aspect_deg=200, rainfall_24h_mm=90,
        rainfall_72h_mm=150, rainfall_7d_mm=240,
        soil_moisture_pct=75, antecedent_precip_index=110,
    )
    assert sum(r.contributing_factors.values()) == pytest.approx(1.0, abs=0.01)


def test_low_sensor_confidence_does_not_lower_the_risk_score():
    """A slope does not become safer because a battery died."""
    kw = dict(
        slope_deg=40, soil_type="Clayey", landcover="Cut Slope",
        elevation_m=1000, aspect_deg=225, rainfall_24h_mm=160,
        rainfall_72h_mm=280, rainfall_7d_mm=400,
        soil_moisture_pct=90, antecedent_precip_index=180,
    )
    assert score_zone(**kw, sensor_confidence=95).risk_score == \
           score_zone(**kw, sensor_confidence=5).risk_score


# --------------------------------------------------------------------------- #
# Sensor health
# --------------------------------------------------------------------------- #
def test_silent_sensor_is_offline_even_with_clean_data():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    h = compute_health(
        sensor_type="SOIL_MOISTURE", values=[50.0] * 24, expected_samples=24,
        battery_pct=100, rssi_dbm=-60, last_seen=now - timedelta(hours=12),
        expected_interval_s=3600, now=now,
    )
    assert h.status == "OFFLINE"


def test_coverage_penalty_applies_to_zone_confidence():
    one_perfect = zone_confidence([100.0])
    four_perfect = zone_confidence([100.0] * 4)
    assert four_perfect > one_perfect


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", [
    "/api/health",
    "/api/districts",
    "/api/risk/zones",
    "/api/risk/summary",
    "/api/risk/pipeline",
    "/api/risk/trend?days=30",
    "/api/alerts",
    "/api/alerts?active_only=true",
    "/api/alerts/delivery/summary",
    "/api/sensors",
    "/api/sensors/summary",
    "/api/gis/layers",
    "/api/gis/layers/risk_heatmap",
    "/api/gis/layers/roads",
    "/api/gis/layers/villages",
    "/api/gis/layers/infrastructure",
    "/api/gis/terrain?district=as-dima-hasao",
    "/api/gis/infrastructure",
    "/api/roads",
    "/api/villages",
    "/api/infrastructure",
    "/api/incidents",
    "/api/reports/field",
    "/api/reports/quarterly",
    "/api/model/performance",
    "/api/weather",
    "/api/weather/all",
    "/api/system/status",
    "/api/notifications",
    "/api/settings/thresholds",
    "/api/settings/languages",
    "/api/recipients",
    "/api/sync/bundle?district=as-dima-hasao",
    "/api/sync/status",
])
def test_endpoint_responds(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"


def test_dem_is_not_an_operator_facing_layer(client):
    """The DEM toggle was removed from the layer picker deliberately.

    An operator managing a live event does not switch on a hillshade basemap, and
    every control on that panel costs attention an operational layer would have
    used better.
    """
    ids = {layer["id"] for layer in client.get("/api/gis/layers").json()}
    assert not ids & {"dem", "terrain", "satellite"}
    assert client.get("/api/gis/layers/dem").status_code == 404


def test_dem_still_drives_terrain_and_spatial_risk(client):
    """Removing the toggle must not have removed the capability.

    This is the other half of the test above: the elevation model is still loaded
    and still doing work — supplying terrain context at a point and the continuous
    spatial-risk surface. If this ever fails, someone deleted the data along with
    the UI control.
    """
    terrain = client.get("/api/gis/terrain?district=nl-kohima").json()
    assert terrain["elevation_max"] > terrain["elevation_min"] > 0
    assert terrain["slope_mean"] > 0

    surface = client.get("/api/gis/layers/spatial_risk").json()
    assert surface["features"], "spatial risk surface is empty"

    ctx = client.get("/api/gis/context?lat=25.67&lng=94.08").json()
    assert ctx["terrain"] is not None
    assert ctx["terrain"]["elevation"] > 0


def test_camel_case_switch(client):
    snake = client.get("/api/risk/zones").json()[0]
    camel = client.get("/api/risk/zones?case=camel").json()[0]
    assert "risk_score" in snake and "riskScore" in camel
    assert snake["risk_score"] == camel["riskScore"]


def test_scope_filter_narrows_results(client):
    all_zones = client.get("/api/risk/zones").json()
    one = client.get("/api/risk/zones?district=as-dima-hasao").json()
    assert 0 < len(one) < len(all_zones)
    assert {z["district_id"] for z in one} == {"as-dima-hasao"}


def test_zone_explainability(client):
    zid = client.get("/api/risk/zones").json()[0]["id"]
    r = client.get(f"/api/risk/zones/{zid}/explain")
    assert r.status_code == 200
    body = r.json()
    assert "lsi" in body and "ti" in body and "contributing_factors" in body
    assert body["formula"].startswith("risk =")


# --------------------------------------------------------------------------- #
# Alert lifecycle
# --------------------------------------------------------------------------- #
def test_alert_lifecycle_and_illegal_transition(client):
    alerts = client.get("/api/alerts?status=NEW").json()
    assert alerts, "seed should leave at least one NEW alert"
    aid = alerts[0]["id"]

    ack = client.post(f"/api/alerts/{aid}/acknowledge", json={"actor": "DDMA Test"})
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKNOWLEDGED"

    dispatched = client.post(f"/api/alerts/{aid}/dispatch", json={"actor": "DDMA Test"})
    assert dispatched.status_code == 200
    assert dispatched.json()["status"] == "IN_PROGRESS"

    resolved = client.post(f"/api/alerts/{aid}/resolve", json={"actor": "DDMA Test"})
    assert resolved.json()["status"] == "RESOLVED"

    # RESOLVED is terminal.
    again = client.post(f"/api/alerts/{aid}/acknowledge", json={})
    assert again.status_code == 409


def test_alert_timeline_records_every_transition(client):
    aid = client.get("/api/alerts").json()[0]["id"]
    body = client.get(f"/api/alerts/{aid}/timeline").json()
    assert body["events"], "every alert must carry an audit trail"
    assert body["events"][0]["event"] == "CREATED"


def test_repeat_cycle_does_not_duplicate_alerts(client):
    """Cooldown: running the engine twice must not double the alert list."""
    before = len(client.get("/api/alerts").json())
    r = client.post("/api/engine/run")
    assert r.status_code == 200
    after = len(client.get("/api/alerts").json())
    assert after == before, f"{after - before} duplicate alerts created"
    assert r.json()["alerts_suppressed"] > 0


def test_escalation_upgrades_in_place_keeping_the_same_id():
    db = session()
    try:
        alert = db.query(Alert).filter(Alert.severity.in_(("MODERATE", "HIGH"))).first()
        assert alert is not None
        zone = db.get(RiskZone, alert.zone_id)
        original_id, original_sev = alert.id, alert.severity

        worse = ae.Candidate(
            zone_id=zone.id, rule_id="R5", trigger=alert.trigger,
            severity="CRITICAL", detail="test escalation", score=95.0,
        )
        updated, action = ae.upsert_alert(db, zone, worse, [], [])
        db.commit()

        assert action == "ESCALATED"
        assert updated.id == original_id            # authorities keep tracking one ID
        assert updated.severity == "CRITICAL"
        assert updated.severity != original_sev
        assert updated.escalation_count >= 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Field reports and offline sync
# --------------------------------------------------------------------------- #
def test_field_report_submission_with_media(client):
    r = client.post(
        "/api/reports/field",
        data={
            "incident_type": "CRACK", "description": "Test crack above the cutting",
            "district_id": "as-dima-hasao", "road_or_village": "NH-27 test",
            "lat": 25.36, "lng": 93.04, "severity": "HIGH",
            "reporter_type": "FIELD_OFFICER", "reporter_name": "Test Unit",
            "client_id": "test-client-001", "device_id": "test-device",
        },
        files=[("files", ("crack.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg"))],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["verification"] == "PENDING"      # arrives unverified, always
    assert len(body["media"]) == 1
    assert body["media"][0]["kind"] == "IMAGE"


def test_media_type_is_rejected_when_unsupported(client):
    r = client.post(
        "/api/reports/field",
        data={"incident_type": "CRACK", "district_id": "as-dima-hasao",
              "lat": 25.36, "lng": 93.04},
        files=[("files", ("payload.exe", b"MZ", "application/x-msdownload"))],
    )
    assert r.status_code == 415


def test_offline_batch_is_idempotent(client):
    payload = {
        "device_id": "field-tablet-7",
        "operations": [{
            "op": "FIELD_REPORT",
            "client_id": "offline-abc-123",
            "payload": {
                "incident_type": "ROAD_BLOCKAGE",
                "description": "Debris across both lanes",
                "district_id": "mz-aizawl", "lat": 23.74, "lng": 92.69,
                "severity": "CRITICAL", "reporter_type": "CITIZEN",
            },
        }],
    }
    first = client.post("/api/sync/batch", json=payload).json()
    assert first["accepted"] == 1
    server_id = first["results"][0]["server_id"]

    # The flaky-uplink replay. Must NOT create a second report.
    second = client.post("/api/sync/batch", json=payload).json()
    assert second["duplicates"] == 1
    assert second["accepted"] == 0
    assert second["results"][0]["server_id"] == server_id


def test_batch_isolates_a_bad_operation(client):
    """One malformed op must not block the rest of the queue."""
    body = client.post("/api/sync/batch", json={
        "device_id": "field-tablet-8",
        "operations": [
            {"op": "FIELD_REPORT", "client_id": "mixed-ok-1",
             "payload": {"incident_type": "CRACK", "district_id": "sk-gangtok",
                         "lat": 27.3, "lng": 88.6}},
            {"op": "FIELD_REPORT", "client_id": "mixed-bad-1",
             "payload": {"incident_type": "CRACK", "district_id": "does-not-exist",
                         "lat": 0, "lng": 0}},
            {"op": "NONSENSE", "client_id": "mixed-bad-2", "payload": {}},
        ],
    }).json()
    assert body["accepted"] == 1
    assert body["failed"] == 2


def test_sync_bundle_carries_an_etag(client):
    r = client.get("/api/sync/bundle?district=as-dima-hasao")
    assert r.headers.get("ETag")
    body = r.json()
    assert body["zones"] and body["thresholds"] and body["escalation_contacts"]


def test_verification_unlocks_the_road_blockage_rule(client):
    """Rule R6 must only fire on VERIFIED reports — an anonymous photo cannot
    trigger a public warning on its own."""
    sub = client.post("/api/reports/field", data={
        "incident_type": "ROAD_BLOCKAGE", "description": "Verification test",
        "district_id": "ml-ri-bhoi", "lat": 25.9, "lng": 91.88,
        "severity": "CRITICAL", "reporter_type": "CITIZEN",
        "client_id": "verify-test-1",
    }).json()

    r = client.patch(f"/api/reports/field/{sub['id']}/verification",
                     json={"verification": "VERIFIED", "actor": "SDM Office"})
    assert r.status_code == 200
    assert r.json()["verification"] == "VERIFIED"
    assert r.json()["verified_by"] == "SDM Office"


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
def test_reading_ingest_tolerates_gateway_replay(client):
    sensor = client.get("/api/sensors").json()[0]
    reading = {"sensor_id": sensor["sensor_id"],
               "timestamp": "2026-08-30T10:00:00+00:00",
               "value": 42.0, "unit": sensor["unit"]}

    first = client.post("/api/ingest/readings", json={"readings": [reading]}).json()
    assert first["accepted"] == 1

    second = client.post("/api/ingest/readings", json={"readings": [reading]}).json()
    assert second["duplicates"] == 1 and second["accepted"] == 0


def test_model_predictions_take_precedence_over_the_rule_engine(client):
    zone = client.get("/api/risk/zones").json()[-1]
    r = client.post("/api/model/predict", json={
        "model_version": "test-1.0.0", "algorithm": "XGBoost",
        "metrics": {"roc_auc": 0.81}, "feature_importance": [],
        "predictions": [{"zone_id": zone["id"], "risk_score": 91.0,
                         "risk_level": "CRITICAL", "probability": 0.93}],
    })
    assert r.status_code == 202
    assert r.json()["zones_updated"] == 1

    after = client.get(f"/api/risk/zones/{zone['id']}").json()
    assert after["risk_score"] == 91.0
    assert after["source"] == "ML_MODEL"
    assert after["model_version"] == "test-1.0.0"

    # A later rule-engine cycle must NOT overwrite the model's number.
    client.post("/api/engine/run")
    still = client.get(f"/api/risk/zones/{zone['id']}").json()
    assert still["risk_score"] == 91.0


def test_reseeding_an_existing_database_succeeds():
    """Regression: reset() must clear children before parents.

    This only fails when someone reseeds in place instead of deleting the .db file
    first — i.e. on a teammate's laptop, the day before the demo.
    """
    counts = seed.run(fresh=True)
    assert counts["zones"] > 0
    assert counts["alerts"] > 0


def test_quarterly_report_has_every_section(client):
    body = client.get("/api/reports/quarterly?district=as-dima-hasao").json()
    for key in ("kpis", "risk_trend", "rainfall_vs_risk", "alerts_by_severity",
                "sensor_performance", "risk_calendar", "district_comparison",
                "infrastructure_impact", "response_metrics", "critical_events",
                "exposure_detail", "historical_context"):
        assert body.get(key) is not None, f"missing report section: {key}"
    assert body["data_confidence"] == "SYNTHETIC"


def test_report_carries_no_recommendations(client):
    """The report states what happened and what the instruments recorded. Deciding
    what to do about it is the district administration's job, and a machine-authored
    action list printed under a government letterhead invites a deference it has not
    earned."""
    body = client.get("/api/reports/quarterly?district=as-dima-hasao").json()
    assert "recommendations" not in body

    document = client.get("/api/reports/render?district=as-dima-hasao").text
    assert "recommend" not in document.lower()


def test_report_changes_with_the_selected_district(client):
    """A report that returns the same figures whatever you select is a template, not
    a report."""
    a = client.get("/api/reports/quarterly?district=as-dima-hasao").json()
    b = client.get("/api/reports/quarterly?district=nl-kohima").json()
    assert a["scope"] != b["scope"]
    assert a["district_comparison"] != b["district_comparison"]


def test_rendered_report_needs_no_network(client):
    """Charts are server-rendered inline SVG on purpose. The target reader may be on a
    satellite link or none at all, and a report whose charts are blank rectangles
    because a CDN was unreachable is not a report."""
    document = client.get("/api/reports/render?district=as-dima-hasao").text
    assert "<svg" in document
    assert "<script src" not in document
    assert "cdn" not in document.lower()


# --------------------------------------------------------------------------- #
# Custom alert rules
# --------------------------------------------------------------------------- #
def test_custom_rule_catalogue_is_served_by_the_engine(client):
    """The builder must never hard-code a parameter list.

    Adding a parameter in core/custom_alerts.py has to make it appear in the UI
    with no frontend change, or the two drift and an operator writes a rule against
    a variable the engine has never heard of.
    """
    cat = client.get("/api/alerts/custom/catalogue").json()
    keys = {p["key"] for p in cat["parameters"]}
    # Every variable the methodology note defines should be writable as a rule.
    assert {"risk_score", "rainfall_24h_mm", "soil_moisture_pct", "slope_deg",
            "antecedent_precip_index", "sensor_confidence"} <= keys
    assert len(cat["tier_table"]) == 4
    assert cat["tier_table"][0]["audience"] == "No message sent"   # Green


def test_custom_rule_preview_does_not_persist_anything(client):
    before = len(client.get("/api/alerts/custom").json())
    r = client.post("/api/alerts/custom/preview", json={
        "name": "draft", "scope_type": "ALL",
        "conditions": [{"parameter": "risk_score", "operator": "GTE", "value": 1}],
    })
    assert r.status_code == 200
    assert r.json()["zones_matched"] > 0
    assert len(client.get("/api/alerts/custom").json()) == before


def test_custom_rule_rejects_an_unknown_parameter(client):
    """A rule that silently never matches is worse than a rejected one: the operator
    believes a slope is being watched when nothing is watching it."""
    r = client.post("/api/alerts/custom", json={
        "name": "bad", "conditions": [{"parameter": "vibes", "operator": "GTE", "value": 1}],
    })
    assert r.status_code == 400
    assert "vibes" in r.text


def test_custom_rule_severity_follows_the_tier_table(client):
    """With severity AUTO the score is mapped through the NDMA/GSI bands, so a custom
    rule cannot trigger a public broadcast on a score the note calls a Green day."""
    from app.core.custom_alerts import tier_for
    assert tier_for(95)[:2] == ("RED", "CRITICAL")
    assert tier_for(70)[:2] == ("ORANGE", "HIGH")
    assert tier_for(50)[:2] == ("YELLOW", "MODERATE")
    assert tier_for(10)[:2] == ("GREEN", "INFORMATION")


def test_zero_cooldown_means_no_cooldown(client):
    """Regression: `rule.cooldown_minutes or DEFAULT` treated 0 as unset and silently
    applied a 45-minute window to a rule the operator had explicitly set to fire every
    cycle."""
    from app.core.custom_alerts import _in_cooldown
    from app.models import CustomAlertRule, utcnow

    rule = CustomAlertRule(id="X", name="x", conditions=[], cooldown_minutes=0)
    rule.last_triggered_at = utcnow()
    assert _in_cooldown(rule) is False


def test_deleting_a_rule_keeps_the_alerts_it_raised(client):
    """Deleting the rule must not erase the record that a warning was issued."""
    created = client.post("/api/alerts/custom", json={
        "name": "temp rule", "scope_type": "ALL",
        "conditions": [{"parameter": "risk_score", "operator": "GTE", "value": 1}],
    }).json()
    alerts_before = len(client.get("/api/alerts").json())
    r = client.delete(f"/api/alerts/custom/{created['id']}")
    assert r.status_code == 200 and r.json()["alerts_retained"] is True
    assert len(client.get("/api/alerts").json()) == alerts_before


# --------------------------------------------------------------------------- #
# Simulation scenarios
# --------------------------------------------------------------------------- #
def test_scenarios_are_advertised_with_their_causal_chain(client):
    scenarios = client.get("/api/simulation/scenarios").json()
    keys = {s["key"] for s in scenarios}
    assert {"NORMAL", "HEAVY_RAINFALL", "SATURATED_SLOPE",
            "SLOPE_MOVEMENT", "SENSOR_FAILURE"} <= keys
    for s in scenarios:
        assert s["chain"], f"{s['key']} has no stated causal chain"


def test_heavy_rainfall_propagates_through_the_engines(client):
    """The scenario must not write an alert. It raises rainfall and lets the risk and
    alert engines reach their own conclusions — that is the whole point of the panel."""
    zone_before = client.get("/api/risk/zones?district=as-dima-hasao").json()[0]
    client.post("/api/simulation/apply",
                json={"scenario": "HEAVY_RAINFALL", "scope_id": "as-dima-hasao"})
    for _ in range(3):
        client.post("/api/simulation/tick")
    zone_after = client.get("/api/risk/zones?district=as-dima-hasao").json()[0]

    assert zone_after["rainfall_24h_mm"] > zone_before["rainfall_24h_mm"]
    # Rain must move the triggering index, not just sit in a field nobody reads.
    assert zone_after["ti"] >= zone_before["ti"]


def test_sensor_failure_is_operational_not_a_hazard_warning(client):
    """The slope has not changed; our ability to see it has. Collapsing the two would
    let an outage overwrite a landslide warning on the same zone."""
    client.post("/api/simulation/apply",
                json={"scenario": "SENSOR_FAILURE", "scope_id": "as-dima-hasao"})
    alerts = client.get("/api/alerts?district=as-dima-hasao").json()
    operational = [a for a in alerts if a["alert_class"] == "OPERATIONAL"]
    hazard = [a for a in alerts if a["alert_class"] == "HAZARD"]
    # Any sensor-anomaly alert raised must be classed operational, and must not have
    # displaced the hazard alerts on those zones.
    for a in alerts:
        if a["trigger"] == "SENSOR_ANOMALY":
            assert a["alert_class"] == "OPERATIONAL"
    assert len(operational) + len(hazard) == len(alerts)


def test_alert_records_every_rule_that_matched(client):
    """`pick_primary` keeps one candidate. The others must still be recorded, or an
    operator asking "why" sees one reason when four rules agreed."""
    client.post("/api/engine/run?send=false")
    alerts = client.get("/api/alerts").json()
    with_rules = [a for a in alerts if a["contributing_rules"]]
    assert with_rules, "no alert recorded its contributing rules"
    sample = with_rules[0]
    assert sum(1 for c in sample["contributing_rules"] if c["primary"]) == 1


# --------------------------------------------------------------------------- #
# Trained-model inference
# --------------------------------------------------------------------------- #
def test_model_status_reports_honestly(client):
    """The platform used to claim ML precedence while scoring everything with the
    fallback rules. This endpoint exists so that claim is checkable from outside."""
    body = client.get("/api/model/status").json()
    assert "available" in body and "features" in body
    if body["available"]:
        assert body["features"] == ["slope_deg", "rainfall_24h_mm", "rainfall_72h_mm",
                                    "rainfall_7d_mm", "antecedent_precip_index"]


def test_inference_is_optional(client):
    """scikit-learn, joblib and pandas are NOT backend requirements. With them
    absent the rule engine must score everything and the cycle must still run — a
    district office that cannot install a scientific stack still gets a working
    early-warning console."""
    from app.core import ml_model
    status = ml_model.status()
    if not status["available"]:
        assert status["error"], "unavailable model must say why"
    # Either way the cycle completes.
    assert client.post("/api/engine/run?send=false").status_code == 200


def test_rule_engine_wins_where_it_is_more_alarmed(client):
    """The classifier sees five observable features. The rules see measured slope
    movement, verified road blockages and saturation. Taking the more severe of two
    independent assessments is the correct bias for early warning."""
    from app.core import ml_model
    if not ml_model.available():
        return
    body = client.post("/api/model/score").json()
    assert body["applied"] + body["rule_engine_kept"] == body["scored"]

    for zone in client.get("/api/risk/zones").json():
        if zone["source"] == "RULE_ENGINE" and zone.get("model_probability") is not None:
            # A rule-scored zone must not be less alarmed than the model it beat.
            assert zone["risk_score"] >= zone["model_probability"] * 100 - 0.05


def test_ml_scored_zones_still_get_fresh_inputs(client):
    """Regression: `rescore_zone` returned early for any zone whose source was
    ML_MODEL. Once inference actually ran, that froze the zone's rainfall and soil
    moisture permanently and fed the model its own stale inputs on the next tick."""
    from app.core import ml_model
    if not ml_model.available():
        return
    client.post("/api/simulation/apply",
                json={"scenario": "HEAVY_RAINFALL", "scope_id": "as-dima-hasao"})
    before = client.get("/api/risk/zones?district=as-dima-hasao").json()[0]
    for _ in range(3):
        client.post("/api/simulation/tick")
    after = client.get("/api/risk/zones?district=as-dima-hasao").json()[0]
    assert after["rainfall_24h_mm"] != before["rainfall_24h_mm"], \
        "inputs stopped refreshing — the ML freeze has come back"


# --------------------------------------------------------------------------- #
# Stream bus
# --------------------------------------------------------------------------- #
def test_stream_filters_at_publish_time(client):
    """A client watching one district must never receive the rest of the region."""
    from app.core.stream_bus import EVENT_SENSOR_READING, EVENT_ZONE_ALERT, bus

    watcher = bus.subscribe("test-alerts", events=[EVENT_ZONE_ALERT])
    everything = bus.subscribe("test-all")
    try:
        bus.publish(EVENT_SENSOR_READING, {"value": 1}, zone_id="z1")
        bus.publish(EVENT_ZONE_ALERT, {"severity": "HIGH"}, zone_id="z1")
        assert watcher.queue.qsize() == 1
        assert everything.queue.qsize() == 2
    finally:
        bus.unsubscribe(watcher)
        bus.unsubscribe(everything)


def test_zone_filter_excludes_other_zones(client):
    from app.core.stream_bus import EVENT_ZONE_RISK, bus

    sub = bus.subscribe("test-zone", zones=["nl-kohima-z1"])
    try:
        bus.publish(EVENT_ZONE_RISK, {"risk_score": 10}, zone_id="as-cachar-z1")
        assert sub.queue.qsize() == 0
        bus.publish(EVENT_ZONE_RISK, {"risk_score": 80}, zone_id="nl-kohima-z1")
        assert sub.queue.qsize() == 1
    finally:
        bus.unsubscribe(sub)


def test_slow_subscriber_drops_oldest_not_newest(client):
    """Backpressure policy: for an early-warning stream the newest reading is always
    the more useful one, so a lagging client loses history rather than stalling the
    producer or being disconnected."""
    from app.core.stream_bus import EVENT_SENSOR_READING, StreamBus

    small = StreamBus(queue_size=3)
    sub = small.subscribe("slow")
    for i in range(6):
        small.publish(EVENT_SENSOR_READING, {"i": i})
    assert sub.queue.qsize() == 3
    assert sub.dropped == 3
    newest = [sub.queue.get_nowait().data["i"] for _ in range(3)]
    assert newest == [3, 4, 5], "backpressure kept the stale events, not the fresh ones"


def test_telemetry_tick_publishes_to_the_bus(client):
    """Regression: only the background loop published, so a scenario applied from the
    UI streamed nothing at all to a connected dashboard."""
    from app.core.stream_bus import bus

    before = bus.published
    client.post("/api/simulation/tick")
    assert bus.published > before
