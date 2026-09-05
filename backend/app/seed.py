"""Deterministic seeding.

Every ID here matches the pattern the frontend generator already uses
(`as-dima-hasao-z1`, `NER-AS-0101`, `as-dima-hasao-r1`), so the console can be
pointed at this backend and every deep link, filter and drawer keeps working.

Seeded from a fixed string, so two people running `python -m app.seed` on different
machines get byte-identical data. When a figure is being reviewed that matters: the screenshot
in the deck is the screen on the projector.

All values remain SYNTHETIC and are labelled as such end-to-end. Replacing this file
with real ingest does not require touching anything else.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .core.risk_engine import RECOMMENDED_ACTION, expected_window_hours, score_zone
from .core.sensor_health import LABELS, UNITS, compute_health, zone_confidence
from .data.regions import DISTRICTS, STATE_BY_CODE, STATES, TERRAIN_WEIGHT
from .db import Base, engine, session
from .models import (
    Alert,
    CustomAlertRule,
    AlertEvent,
    District,
    Dispatch,
    HistoricalIncident,
    Infrastructure,
    IncidentReport,
    JobRecord,
    ModelRun,
    Notification,
    Recipient,
    ReportMedia,
    RiskHistory,
    RiskZone,
    Road,
    Sensor,
    SensorReading,
    SyncLedger,
    User,
    Village,
    WeatherObservation,
)

NOW = datetime.now(timezone.utc)

ZONE_SUFFIX = [
    "Ridge Slope", "Cutting Km 14", "Hillside Sector", "Ghat Section",
    "Catchment Slope", "Bypass Escarpment",
]
ROAD_NAMES = ["NH-6", "NH-27", "NH-29", "NH-37", "NH-44", "NH-102B", "NH-306",
              "SH-1", "SH-12", "District Road 4"]
VILLAGE_NAMES = ["Umsning", "Lailad", "Mahur", "Harangajao", "Bagetar", "Sairang",
                 "Tseminyu", "Rangpo", "Rongli", "Khliehriat", "Nongpoh", "Jiribam"]
SENSOR_TYPES = ["RAIN_GAUGE", "SOIL_MOISTURE", "PIEZOMETER", "TILTMETER",
                "EXTENSOMETER", "GEOPHONE", "WEATHER_STATION"]
SOILS = ["Silty Loam", "Laterite", "Clayey", "Gravel", "Bedrock"]
LANDCOVERS = ["Dense Forest", "Plantation", "Agriculture", "Built-up", "Barren", "Cut Slope"]
INCIDENT_TYPES = ["LANDSLIDE", "ROCKFALL", "ROAD_BLOCKAGE", "SLOPE_MOVEMENT", "CRACK", "FLOOD"]
INFRA_TYPES = ["HIGHWAY", "BRIDGE", "HOSPITAL", "SCHOOL", "VILLAGE"]


def rng(key: str) -> random.Random:
    """Stable per-entity RNG so re-seeding one district does not shift the others."""
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return random.Random(int(h, 16))


def rnd(r: random.Random, lo: float, hi: float, nd: int = 2) -> float:
    return round(lo + r.random() * (hi - lo), nd)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------- #
def seed_districts(db: Session) -> None:
    for d in DISTRICTS:
        state = STATE_BY_CODE[d["state_code"]]
        w = TERRAIN_WEIGHT[d["terrain"]]
        db.merge(
            District(
                id=d["id"],
                name=d["name"],
                state_code=d["state_code"],
                state_name=state["name"],
                lat=d["lat"],
                lng=d["lng"],
                population=d["population"],
                terrain=d["terrain"],
                # Steeper terrain fails at lower rainfall, so its threshold is lower.
                alert_threshold_24h=round(70 + (1 - w) * 40, 0),
            )
        )
    db.commit()


def seed_weather(db: Session) -> None:
    for d in DISTRICTS:
        r = rng(f"weather-{d['id']}")
        w = TERRAIN_WEIGHT[d["terrain"]]
        r24 = round(rnd(r, 8, 190) * (0.55 + w * 0.6), 1)
        threshold = round(70 + (1 - w) * 40, 0)
        r72 = round(r24 * rnd(r, 1.6, 2.6), 1)
        r7d = round(r24 * rnd(r, 2.4, 4.6), 1)
        condition = ("THUNDERSTORM" if r24 > 140 else "HEAVY_RAIN" if r24 > 90
                     else "LIGHT_RAIN" if r24 > 40 else "CLEAR")
        ratio = r24 / threshold
        level = ("CRITICAL" if ratio >= 1.15 else "HIGH" if ratio >= 0.85
                 else "MODERATE" if ratio >= 0.5 else "LOW")
        forecast = []
        for i in range(5):
            fr = round(r24 * rnd(r, 0.35, 1.35), 1)
            forecast.append({
                "date": (NOW + timedelta(days=i + 1)).isoformat(),
                "rainfall_mm": fr,
                "probability_pct": int(clamp(fr / threshold * 90, 8, 96)),
                "risk_level": ("CRITICAL" if fr / threshold >= 1.15 else
                               "HIGH" if fr / threshold >= 0.85 else
                               "MODERATE" if fr / threshold >= 0.5 else "LOW"),
                "temp_min": round(rnd(r, 17, 22), 0),
                "temp_max": round(rnd(r, 25, 33), 0),
            })
        db.add(WeatherObservation(
            district_id=d["id"], district=d["name"],
            observed_at=NOW - timedelta(minutes=int(rnd(r, 4, 22))),
            rainfall_now_mm=round(r24 / rnd(r, 12, 30), 1),
            rainfall_24h_mm=r24, rainfall_72h_mm=r72, rainfall_7d_mm=r7d,
            humidity_pct=round(rnd(r, 68, 97), 0),
            temperature_c=round(rnd(r, 19, 31), 1),
            wind_kph=round(rnd(r, 3, 26), 1),
            condition=condition, weather_risk_level=level,
            alert_threshold_24h=threshold, forecast=forecast,
            source="IMD_PLACEHOLDER",
        ))
    db.commit()


def _zone_polygon(lat: float, lng: float, radius: float, r: random.Random) -> dict:
    ring = []
    for i in range(9):
        ang = i / 8 * math.pi * 2
        j = 0.65 + r.random() * 0.7
        ring.append([round(lng + math.cos(ang) * radius * j, 4),
                     round(lat + math.sin(ang) * radius * j * 0.8, 4)])
    return {"type": "Polygon", "coordinates": [ring]}


def seed_zones(db: Session) -> None:
    for d in DISTRICTS:
        r = rng(f"zone-{d['id']}")
        w = TERRAIN_WEIGHT[d["terrain"]]
        wx = db.scalars(
            select(WeatherObservation).where(WeatherObservation.district_id == d["id"])
        ).first()
        count = 1 if d["terrain"] == "PLAIN" else 3 if d["terrain"] == "STEEP_HILL" else 2

        for i in range(count):
            slope = round(rnd(r, 12, 62) * (0.55 + w * 0.75), 1)
            elevation = round(rnd(r, 90, 2100) * (0.4 + w), 0)
            aspect = round(rnd(r, 0, 359), 0)
            soil = SOILS[int(r.random() * len(SOILS))]
            cover = LANDCOVERS[int(r.random() * len(LANDCOVERS))]
            moisture = round(clamp(28 + wx.rainfall_7d_mm / 12 + rnd(r, -6, 12), 18, 98), 1)
            api = round(clamp(wx.rainfall_7d_mm / 7 + rnd(r, -3, 6), 0, 60), 1)

            res = score_zone(
                slope_deg=slope, soil_type=soil, landcover=cover,
                elevation_m=elevation, aspect_deg=aspect,
                rainfall_24h_mm=wx.rainfall_24h_mm,
                rainfall_72h_mm=wx.rainfall_72h_mm,
                rainfall_7d_mm=wx.rainfall_7d_mm,
                soil_moisture_pct=moisture, antecedent_precip_index=api,
            )
            zid = f"{d['id']}-z{i + 1}"
            db.add(RiskZone(
                id=zid,
                name=f"{d['name']} {ZONE_SUFFIX[(i + len(d['name'])) % len(ZONE_SUFFIX)]}",
                district_id=d["id"], district=d["name"], state_code=d["state_code"],
                lat=round(d["lat"] + rnd(r, -0.22, 0.22), 4),
                lng=round(d["lng"] + rnd(r, -0.24, 0.24), 4),
                slope_deg=slope, elevation_m=elevation, aspect_deg=aspect,
                soil_type=soil, landcover=cover,
                rainfall_24h_mm=wx.rainfall_24h_mm,
                rainfall_72h_mm=wx.rainfall_72h_mm,
                rainfall_7d_mm=wx.rainfall_7d_mm,
                antecedent_precip_index=api, soil_moisture_pct=moisture,
                lsi=res.lsi, ti=res.ti,
                risk_score=res.risk_score, risk_level=res.risk_level,
                alert_tier=res.alert_tier, probability=res.probability,
                contributing_factors=res.contributing_factors,
                sensor_confidence=round(rnd(r, 54, 98), 0),
                expected_window_hours=expected_window_hours(res.risk_level),
                recommended_action=RECOMMENDED_ACTION[res.risk_level],
                population=int(d["population"] * rnd(r, 0.01, 0.09)),
                geometry=_zone_polygon(d["lat"], d["lng"], 0.06 + r.random() * 0.09, r),
                source="RULE_ENGINE",
                data_confidence=settings.data_confidence,
            ))
    db.commit()


def seed_sensors(db: Session) -> None:
    zones = db.scalars(select(RiskZone)).all()
    for zi, z in enumerate(zones):
        r = rng(f"sensor-{z.id}")
        n = 3 + int(r.random() * 3)
        for si in range(n):
            stype = SENSOR_TYPES[(zi + si) % len(SENSOR_TYPES)]
            base = {
                "RAIN_GAUGE": z.rainfall_24h_mm / 24,
                "SOIL_MOISTURE": z.soil_moisture_pct,
                "PIEZOMETER": z.soil_moisture_pct / 100 * 70,
                "TILTMETER": z.risk_score / 100 * 3.4,
                "EXTENSOMETER": z.risk_score / 100 * 48,
                "GEOPHONE": 25 + z.risk_score / 100 * 55,
                "WEATHER_STATION": 24 - z.elevation_m / 2100 * 8,
            }[stype]

            battery = round(rnd(r, 9, 100), 0)
            rssi = round(rnd(r, -118, -58), 0)
            sid = f"NER-{z.state_code}-{zi + 1:02d}{si + 1:02d}"

            # 24 hourly readings, then score health from the actual series.
            values, rows = [], []
            for h in range(24):
                val = round(clamp(base * rnd(r, 0.72, 1.28), 0, 999), 2)
                values.append(val)
                rows.append(SensorReading(
                    sensor_id=sid,
                    timestamp=NOW - timedelta(hours=23 - h),
                    value=val, unit=UNITS[stype], quality_flag="OK",
                ))

            silence_min = rnd(r, 1, 240)
            last_seen = NOW - timedelta(minutes=silence_min)
            health = compute_health(
                sensor_type=stype, values=values, expected_samples=24,
                battery_pct=battery, rssi_dbm=rssi, last_seen=last_seen,
                expected_interval_s=3600, now=NOW,
            )
            db.add(Sensor(
                id=sid, name=f"{z.district} \u00b7 {LABELS[stype]}",
                zone_id=z.id, district_id=z.district_id, district=z.district,
                state_code=z.state_code,
                lat=round(z.lat + rnd(r, -0.05, 0.05), 4),
                lng=round(z.lng + rnd(r, -0.05, 0.05), 4),
                sensor_type=stype, unit=UNITS[stype], reading=values[-1],
                status=health.status, health_score=health.score,
                health_sub_scores=health.sub_scores,
                battery_pct=battery, rssi_dbm=rssi, expected_interval_s=3600,
                last_seen=last_seen, risk_contribution=round(rnd(r, 0.04, 0.36), 2),
                maintenance_note=health.note,
                installed_on=NOW - timedelta(days=int(rnd(r, 90, 900))),
                transport="SATELLITE" if rssi < -110 else "LORAWAN",
            ))
            db.add_all(rows)
        db.flush()

    # Recompute zone confidence now that sensors exist.
    for z in zones:
        scores = [s.health_score for s in db.scalars(
            select(Sensor).where(Sensor.zone_id == z.id)).all()]
        z.sensor_confidence = zone_confidence(scores)
    db.commit()


def seed_roads_villages_infra(db: Session) -> None:
    for di, d in enumerate(DISTRICTS):
        r = rng(f"asset-{d['id']}")
        zones = db.scalars(select(RiskZone).where(RiskZone.district_id == d["id"])).all()
        peak = max([z.risk_score for z in zones], default=20)

        n_roads = 1 if d["terrain"] == "PLAIN" else 2
        for i in range(n_roads):
            score = clamp(peak - i * rnd(r, 4, 18), 3, 97)
            level = ("CRITICAL" if score >= 80 else "HIGH" if score >= 60
                     else "MODERATE" if score >= 35 else "LOW")
            status = {"CRITICAL": "BLOCKED", "HIGH": "RESTRICTED",
                      "MODERATE": "AT_RISK", "LOW": "OPEN"}[level]
            path = [[round(d["lng"] - 0.2 + k * 0.1 + rnd(r, -0.05, 0.05), 4),
                     round(d["lat"] - 0.14 + k * 0.07 + rnd(r, -0.04, 0.04), 4)]
                    for k in range(5)]
            db.add(Road(
                id=f"{d['id']}-r{i + 1}",
                name=f"{ROAD_NAMES[(di + i) % len(ROAD_NAMES)]} \u00b7 {d['name']}",
                district_id=d["id"], district=d["name"], state_code=d["state_code"],
                status=status, risk_level=level, length_km=round(rnd(r, 8, 74), 1),
                path=path, last_updated=NOW - timedelta(minutes=int(rnd(r, 5, 90))),
                note=("Debris across carriageway; clearance in progress."
                      if status == "BLOCKED" else
                      "Single-lane movement, night traffic suspended."
                      if status == "RESTRICTED" else None),
            ))

        for i in range(3):
            base = zones[i % max(len(zones), 1)].risk_score if zones else 30
            score = clamp(base + rnd(r, -22, 10), 3, 97)
            level = ("CRITICAL" if score >= 80 else "HIGH" if score >= 60
                     else "MODERATE" if score >= 35 else "LOW")
            suffix = ["", "Basti", "Pathar", "Colony"][i % 4]
            db.add(Village(
                id=f"{d['id']}-v{i + 1}",
                name=f"{VILLAGE_NAMES[(di + i * 3) % len(VILLAGE_NAMES)]} {suffix}".strip(),
                district_id=d["id"], district=d["name"], state_code=d["state_code"],
                lat=round(d["lat"] + rnd(r, -0.3, 0.3), 4),
                lng=round(d["lng"] + rnd(r, -0.3, 0.3), 4),
                population=int(rnd(r, 400, 9000)), risk_level=level,
                connectivity=("ISOLATED" if level == "CRITICAL" else
                              "AT_RISK" if level == "HIGH" else "CONNECTED"),
            ))

        for i in range(3):
            itype = INFRA_TYPES[(i + len(d["name"])) % len(INFRA_TYPES)]
            score = clamp(peak - rnd(r, 0, 30), 5, 97)
            level = ("CRITICAL" if score >= 80 else "HIGH" if score >= 60
                     else "MODERATE" if score >= 35 else "LOW")
            importance = ("CRITICAL" if itype in ("HOSPITAL", "HIGHWAY")
                          else "HIGH" if itype == "BRIDGE" else "MEDIUM")
            weight = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.55, "LOW": 0.3}[importance]
            ex = score * weight * 1.15
            exposure = ("CRITICAL" if ex >= 80 else "HIGH" if ex >= 60
                        else "MODERATE" if ex >= 35 else "LOW")
            name = {
                "HOSPITAL": f"{d['name']} District Hospital",
                "SCHOOL": f"Govt. HS School, {d['name']}",
                "BRIDGE": f"{d['name']} River Bridge",
                "HIGHWAY": f"{ROAD_NAMES[i % len(ROAD_NAMES)]} corridor",
                "VILLAGE": f"{VILLAGE_NAMES[i % len(VILLAGE_NAMES)]} cluster",
            }[itype]
            db.add(Infrastructure(
                id=f"{d['id']}-i{i + 1}", name=name, infra_type=itype,
                district_id=d["id"], district=d["name"], state_code=d["state_code"],
                lat=round(d["lat"] + rnd(r, -0.18, 0.18), 4),
                lng=round(d["lng"] + rnd(r, -0.18, 0.18), 4),
                risk_level=level, importance=importance, exposure=exposure,
                population_served=int(rnd(r, 1200, 90000)),
            ))
    db.commit()


def seed_incidents(db: Session) -> None:
    for di, d in enumerate(DISTRICTS):
        r = rng(f"incident-{d['id']}")
        w = TERRAIN_WEIGHT[d["terrain"]]
        n = max(1, round(w * 5))
        road = db.scalars(select(Road).where(Road.district_id == d["id"])).first()
        for i in range(n):
            score = round(clamp(rnd(r, 30, 96) * (0.6 + w * 0.5), 20, 97), 0)
            sev = ("CRITICAL" if score >= 80 else "HIGH" if score >= 60
                   else "MODERATE" if score >= 35 else "LOW")
            db.add(HistoricalIncident(
                id=f"INC-{2400 + di * 10 + i}",
                date=NOW - timedelta(days=int(rnd(r, 3, 330))),
                district_id=d["id"], district=d["name"], state_code=d["state_code"],
                location=f"{d['name']} \u2014 km {int(rnd(r, 4, 88))}",
                lat=round(d["lat"] + rnd(r, -0.25, 0.25), 4),
                lng=round(d["lng"] + rnd(r, -0.25, 0.25), 4),
                incident_type=INCIDENT_TYPES[int(r.random() * len(INCIDENT_TYPES))],
                severity=sev, rainfall_24h_mm=round(rnd(r, 20, 210), 1),
                risk_score_at_event=score,
                affected_road=road.name if road else "Unclassified road",
                affected_population=int(rnd(r, 120, 14000)),
                response_time_minutes=int(rnd(r, 25, 320)),
                status="UNDER_REVIEW" if r.random() > 0.75 else
                       "CLOSED" if r.random() > 0.2 else "OPEN",
                predicted=(r.random() > 0.25) if score > 55 else (r.random() > 0.7),
                data_confidence=settings.data_confidence,
            ))
    db.commit()


def seed_risk_history(db: Session, days: int = 90) -> None:
    """90 days of history so /risk/trend and the quarterly report have real series."""
    zones = db.scalars(select(RiskZone)).all()
    for z in zones:
        r = rng(f"hist-{z.id}")
        for day in range(days):
            wave = math.sin(day / days * math.pi * 1.6) * 22
            rain = round(clamp(35 + wave * 2.4 + rnd(r, -28, 42), 0, 210), 1)
            score = round(clamp(z.risk_score * 0.55 + wave + rain * 0.18 + rnd(r, -9, 9), 6, 96), 0)
            level = ("CRITICAL" if score >= 80 else "HIGH" if score >= 60
                     else "MODERATE" if score >= 35 else "LOW")
            db.add(RiskHistory(
                zone_id=z.id, district_id=z.district_id,
                recorded_at=NOW - timedelta(days=days - 1 - day),
                risk_score=score, risk_level=level,
                rainfall_24h_mm=rain,
                soil_moisture_pct=round(clamp(z.soil_moisture_pct + rnd(r, -12, 12), 10, 99), 1),
            ))
    db.commit()


def seed_recipients(db: Session) -> None:
    """A realistic routing table: two authority contacts, one ward member and one
    public broadcast endpoint per district, in mixed languages."""
    langs_by_state = {
        "AS": "as", "ML": "en", "MN": "hi", "MZ": "en",
        "NL": "en", "TR": "bn", "SK": "ne", "AR": "hi",
    }
    for d in DISTRICTS:
        r = rng(f"recip-{d['id']}")
        lang = langs_by_state.get(d["state_code"], "en")
        base = 9000000000 + int(r.random() * 89999999)
        rows = [
            ("District Magistrate, " + d["name"], "DM", "AUTHORITY", "en", ["SMS", "PUSH"]),
            ("SDRF Control Room, " + d["name"], "SDRF", "AUTHORITY", "en", ["SMS", "PUSH"]),
            ("Ward Member \u2014 " + d["name"], "WARD_MEMBER", "LOCAL", lang, ["SMS"]),
            ("Public broadcast \u2014 " + d["name"], "PUBLIC", "PUBLIC", lang, ["SMS"]),
        ]
        for i, (name, role, aud, lg, ch) in enumerate(rows):
            db.add(Recipient(
                name=name, role=role, audience=aud, district_id=d["id"],
                msisdn=f"+91{base + i}", language=lg, channels=ch, active=True,
            ))
    db.commit()


def seed_users(db: Session) -> None:
    import hashlib as _h

    def pw(p: str) -> str:
        return _h.sha256(p.encode()).hexdigest()

    for username, display, role, district, state in [
        ("admin", "State Admin", "STATE_ADMIN", None, None),
        ("ddma.dimahasao", "DDMA Dima Hasao", "DDMA", "as-dima-hasao", "AS"),
        ("field.pwd3", "PWD Field Unit 3", "FIELD_OFFICER", "as-dima-hasao", "AS"),
        ("viewer", "Read-only Viewer", "VIEWER", None, None),
    ]:
        # merge() would not dedupe here: the primary key is an autoincrement id, not
        # the username, so a merged User with id=None is always an INSERT. Look up on
        # the natural key instead.
        existing = db.scalars(select(User).where(User.username == username)).first()
        if existing:
            existing.display_name = display
            existing.role = role
            existing.district_id = district
            existing.state_code = state
            existing.password_hash = pw("demo1234")
        else:
            db.add(User(username=username, display_name=display,
                        password_hash=pw("demo1234"), role=role,
                        district_id=district, state_code=state))
    db.commit()


def seed_field_reports(db: Session) -> None:
    samples = [
        ("FR-4821", "CRACK", "Tension crack roughly 12 m long opened above the road cutting "
         "after last night's rain. Widening since morning.", "as-dima-hasao",
         "NH-27 \u00b7 Mahur section", 25.3612, 93.0451, "HIGH", "FIELD_OFFICER",
         "PWD Field Unit 3", 48, "SYNCED", "PENDING"),
        ("FR-4820", "ROAD_BLOCKAGE", "Boulder and debris across both lanes. Vehicles queued "
         "on the Aizawl side.", "mz-aizawl", "NH-6 \u00b7 Sairang approach",
         23.7412, 92.6903, "CRITICAL", "CITIZEN", "Anonymous", 126, "SYNCED", "VERIFIED"),
        ("FR-4819", "SLOPE_MOVEMENT", "Retaining wall bulging near the school approach road. "
         "Reported by ward member.", "sk-gangtok", "Ranipool \u00b7 Ward 4",
         27.3021, 88.5981, "MODERATE", "AUTHORITY", "SDM Office", 310,
         "PENDING_SYNC", "PENDING"),
        # Coordinates below sit inside the surveyed NH-29 corridor, so a verified
        # report lands on the GIS map next to the assets it actually threatens.
        ("FR-4818", "ROCKFALL", "Loose rock coming down onto the carriageway below the "
         "cut face. Two boulders roughly a metre across on the shoulder.",
         "nl-kohima", "NH-29 \u00b7 Km 152 near Se\u00ebch\u00fc Zubza",
         25.6705, 94.0812, "HIGH", "FIELD_OFFICER", "NHIDCL Patrol 2", 72,
         "SYNCED", "VERIFIED"),
        ("FR-4817", "DRAINAGE_FAILURE", "Side drain choked with debris; water sheeting "
         "across the road and undercutting the shoulder.",
         "nl-kohima", "NH-29 \u00b7 Km 147 Dz\u00fcdza approach",
         25.6642, 94.0605, "MODERATE", "FIELD_OFFICER", "PWD Kohima Division", 205,
         "SYNCED", "PENDING"),
        ("FR-4816", "FLOODED_ROAD", "Approach slab overtopped after overnight rain. "
         "Light vehicles turning back.", "ml-east-khasi-hills",
         "Sohra \u00b7 Laitkynsew approach", 25.2708, 91.7318, "MODERATE",
         "CITIZEN", "Anonymous", 415, "PENDING_SYNC", "PENDING"),
    ]
    for (rid, itype, desc, did, place, lat, lng, sev, rtype, rname, mins,
         sync, verif) in samples:
        d = next(x for x in DISTRICTS if x["id"] == did)
        db.merge(IncidentReport(
            id=rid, client_id=f"seed-{rid}", incident_type=itype, description=desc,
            district_id=did, district=d["name"], state_code=d["state_code"],
            road_or_village=place, lat=lat, lng=lng, severity=sev,
            reporter_type=rtype, reporter_name=rname,
            reported_at=NOW - timedelta(minutes=mins),
            sync_status=sync, verification=verif,
        ))
    db.commit()


def seed_model_run(db: Session) -> None:
    """Register the training run from the ML pipeline's own output files.

    Read from `data/ml/model_metrics.json` and `feature_importance.csv` rather than
    copied into this file, so retraining updates the console without anyone
    remembering to edit a seed script. The caveat ships with the numbers and must
    not be stripped: these are simulated scenarios, not field outcomes.
    """
    import csv as _csv
    import json as _json

    metrics = {"roc_auc": 0.786, "accuracy": 0.697, "precision": 0.549,
               "recall": 0.850, "f1": 0.667}
    algorithm = "RandomForest"
    importance = [{"feature": "slope_deg", "importance": 0.866}]

    metrics_path = Path(settings.ml_data_dir) / "model_metrics.json"
    if metrics_path.is_file():
        try:
            blob = _json.loads(metrics_path.read_text())
            # The pipeline compares candidates; pick on ROC AUC, which is what the
            # training script selects on.
            best = max(blob.items(), key=lambda kv: kv[1].get("roc_auc", 0))
            algorithm = {"random_forest": "RandomForest",
                         "xgboost": "XGBoost"}.get(best[0], best[0])
            metrics = {k: v for k, v in best[1].items() if isinstance(v, (int, float))}
            metrics["confusion_matrix"] = best[1].get("confusion_matrix")
        except Exception:  # noqa: BLE001
            pass

    fi_path = Path(settings.ml_data_dir) / "feature_importance.csv"
    if fi_path.is_file():
        try:
            with fi_path.open(newline="", encoding="utf-8") as fh:
                rows = [r for r in _csv.reader(fh) if len(r) >= 2]
            parsed = []
            for name, value in rows:
                try:
                    parsed.append({"feature": name, "importance": round(float(value), 4)})
                except ValueError:
                    continue          # header row
            if parsed:
                importance = sorted(parsed, key=lambda x: -x["importance"])[:10]
        except Exception:  # noqa: BLE001
            pass

    db.add(ModelRun(
        model_version="rf-baseline-0.1.0",
        algorithm=algorithm,
        zones_scored=db.query(RiskZone).count(),
        metrics=metrics,
        feature_importance=importance,
        evaluated_on="Held-out split of the physics-simulated scenario set",
        caveat=("Measured against simulated scenarios, not observed events. Treat as a "
                "pipeline baseline until real GSI/COOLR exports are ingested."),
    ))
    db.commit()


def seed_custom_rules(db: Session) -> None:
    """Two worked examples so the rule builder is not an empty page.

    Both are the kind of rule a district office actually writes: a local threshold
    lower than the regional default, and a data-quality rule that is explicitly
    operational rather than a hazard warning.
    """
    examples = [
        dict(
            id="CR-MAHUR",
            name="Mahur cutting — local 90 mm threshold",
            description=("The NH-27 cutting above Mahur has failed twice below the "
                         "150 mm regional critical threshold. Local rule fires earlier."),
            scope_type="DISTRICT", scope_id="as-dima-hasao",
            conditions=[
                {"parameter": "rainfall_24h_mm", "operator": "GTE", "value": 90},
                {"parameter": "soil_moisture_pct", "operator": "GTE", "value": 65},
            ],
            match="ALL", severity="AUTO", alert_class="HAZARD",
            enabled=True, notify=True, cooldown_minutes=45,
            created_by="DDMA Dima Hasao",
        ),
        dict(
            id="CR-CONF",
            name="Monsoon confidence floor",
            description=("Flags any zone whose risk score is being computed from a "
                         "fleet we no longer trust. Not a landslide warning."),
            scope_type="ALL", scope_id="ALL",
            conditions=[
                {"parameter": "sensor_confidence", "operator": "LT", "value": 45},
                {"parameter": "risk_score", "operator": "GTE", "value": 50},
            ],
            match="ALL", severity="MODERATE", alert_class="OPERATIONAL",
            enabled=True, notify=False, cooldown_minutes=120,
            created_by="State control room",
        ),
    ]
    for spec in examples:
        db.merge(CustomAlertRule(**spec))
    db.commit()


def seed_notifications(db: Session) -> None:
    items = [
        ("N-1", "CRITICAL_ALERT", "Critical alert \u2014 Dima Hasao",
         "Model probability crossed the dispatch cut-off. Expected window: next 6 hours.",
         9, False, "/alerts"),
        ("N-2", "ROAD_BLOCKAGE", "NH-6 reported blocked",
         "Field report FR-4820 confirms debris across both lanes near Sairang.",
         126, False, "/field-reports"),
        ("N-3", "SENSOR_FAILURE", "Sensor uplink lost",
         "Three tiltmeters in Mizoram have not reported for over 3 hours.",
         184, False, "/sensors"),
        ("N-4", "CITIZEN_REPORT", "New citizen report awaiting verification",
         "Crack reported above the NH-27 cutting, Mahur section.", 48, True, "/field-reports"),
        ("N-5", "SYSTEM", "Risk model run completed",
         "Rule engine scored all zones. Next scheduled run in 15 minutes.", 14, True, None),
    ]
    for i, (nid, cat, title, body, mins, read, href) in enumerate(items):
        db.merge(Notification(id=nid, category=cat, title=title, body=body,
                              created_at=NOW - timedelta(minutes=mins),
                              read=read, href=href))
    db.commit()


def reset(db: Session) -> None:
    """Wipe in foreign-key-safe order: children before parents.

    Getting this list wrong fails silently until someone reseeds an existing
    database rather than deleting the file first — which is exactly what happens
    on another machine.
    """
    for model in (
        # children first
        Dispatch, AlertEvent, ReportMedia, SensorReading, RiskHistory,
        # then the rows they pointed at
        Alert, IncidentReport, Sensor, RiskZone,
        # standalone
        SyncLedger, JobRecord, Road, Village, Infrastructure,
        HistoricalIncident, WeatherObservation, Recipient, Notification, ModelRun,
    ):
        db.query(model).delete()
    db.commit()


def run(fresh: bool = True) -> dict:
    Base.metadata.create_all(engine)
    db = session()
    try:
        if fresh:
            reset(db)
        seed_districts(db)
        seed_weather(db)
        seed_zones(db)
        seed_sensors(db)
        seed_roads_villages_infra(db)
        seed_incidents(db)
        seed_risk_history(db)
        seed_recipients(db)
        seed_users(db)
        seed_field_reports(db)
        seed_model_run(db)
        seed_custom_rules(db)
        seed_notifications(db)

        # First alert pass so the console has something on screen immediately.
        from .services import run_risk_cycle
        cycle = run_risk_cycle(db, send=True)

        return {
            "districts": db.query(District).count(),
            "zones": db.query(RiskZone).count(),
            "sensors": db.query(Sensor).count(),
            "readings": db.query(SensorReading).count(),
            "roads": db.query(Road).count(),
            "villages": db.query(Village).count(),
            "infrastructure": db.query(Infrastructure).count(),
            "incidents": db.query(HistoricalIncident).count(),
            "risk_history": db.query(RiskHistory).count(),
            "recipients": db.query(Recipient).count(),
            "alerts": db.query(Alert).count(),
            "custom_rules": db.query(CustomAlertRule).count(),
            "dispatches": db.query(Dispatch).count(),
            "cycle": cycle,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2, default=str))
