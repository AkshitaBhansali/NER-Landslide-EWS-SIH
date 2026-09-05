"""/api/gis and asset endpoints.

Everything spatial is served as real GeoJSON FeatureCollections. The layer
registry in the frontend already reads `available` and `source_hint`, so a layer
becomes live by flipping a flag here — no UI change.
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from .. import serializers as S
from .. import services
from ..core import gis_store
from ..data.regions import DISTRICT_BY_ID, TERRAIN_WEIGHT
from ..deps import Scope, Session, get_case, get_db, get_scope, respond
from ..models import (
    HistoricalIncident,
    IncidentReport,
    Infrastructure,
    RiskZone,
    Road,
    Sensor,
    Village,
)

router = APIRouter(prefix="/api", tags=["gis"])

# The user-facing layer picker. DEM / terrain shading / satellite imagery are
# deliberately NOT in this list.
#
# The DEM has not gone anywhere: `core/gis_store.py` loads the corridor elevation
# raster and its seven derivatives, and they are used for slope and elevation in
# the risk inputs, for zone terrain context, for the spatial-risk surface below,
# and for the topographic section of the quarterly report. What was removed is the
# *toggle* — an operator managing an active landslide event does not need a
# hillshade basemap, and every switch on this panel costs attention that a fifth
# operational layer would have used better.
LAYERS = [
    {"id": "risk_heatmap", "label": "Risk zones",
     "description": "Scored slope units, shaded by current risk band.",
     "available": True, "default_on": True, "group": "RISK",
     "source_hint": "GET /api/gis/layers/risk_heatmap -> FeatureCollection<Polygon>"},
    {"id": "spatial_risk", "label": "Spatial risk surface",
     "description": "Continuous corridor risk grid from the GIS pipeline, by timestep.",
     "available": True, "default_on": False, "group": "RISK",
     "source_hint": "GET /api/gis/layers/spatial_risk?timestep= -> FeatureCollection<Polygon>"},
    {"id": "sensors", "label": "Sensors",
     "description": "Deployed sensor positions coloured by health status.",
     "available": True, "default_on": True, "group": "ASSETS",
     "source_hint": "GET /api/gis/layers/sensors -> FeatureCollection<Point>"},
    {"id": "roads", "label": "Roads",
     "description": "Highway and district road segments with connectivity status.",
     "available": True, "default_on": True, "group": "ASSETS",
     "source_hint": "GET /api/gis/layers/roads -> FeatureCollection<LineString>"},
    {"id": "settlements", "label": "Settlements",
     "description": "Habitations with population and isolation status.",
     "available": True, "default_on": True, "group": "ASSETS",
     "source_hint": "GET /api/gis/layers/settlements -> FeatureCollection<Point>"},
    {"id": "rivers", "label": "Rivers",
     "description": "Watercourses with toe-scour and flash-flood exposure.",
     "available": True, "default_on": False, "group": "ASSETS",
     "source_hint": "GET /api/gis/layers/rivers -> FeatureCollection<LineString>"},
    {"id": "infrastructure", "label": "Critical infrastructure",
     "description": "Bridges, hospitals, schools and transmission assets by importance.",
     "available": True, "default_on": False, "group": "ASSETS",
     "source_hint": "GET /api/gis/layers/infrastructure -> FeatureCollection<Point>"},
    {"id": "incidents", "label": "Incidents",
     "description": "Verified field reports and recorded historical events.",
     "available": True, "default_on": True, "group": "RISK",
     "source_hint": "GET /api/gis/layers/incidents -> FeatureCollection<Point>"},
    {"id": "rainfall", "label": "Rainfall",
     "description": "24-hour accumulation against each district's alert threshold.",
     "available": True, "default_on": False, "group": "RISK",
     "source_hint": "GET /api/gis/layers/rainfall -> FeatureCollection<Point>"},
]

# Aliases kept so an older client asking for "villages" still gets settlements
# rather than a 404 during a rolling deploy.
LAYER_ALIASES = {"villages": "settlements", "critical_assets": "infrastructure"}


def _corridor_in_scope(state_code: str | None, district_id: str | None) -> bool:
    """The corridor export covers Kohima district. Include it only when the current
    scope would show it, so a Meghalaya filter does not put NH-29 on the map."""
    if district_id and district_id != "ALL":
        return district_id == gis_store.CORRIDOR_DISTRICT_ID
    if state_code and state_code != "ALL":
        return state_code == "NL"
    return True


def fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def point(lng: float, lat: float, props: dict) -> dict:
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": props}


@router.get("/gis/layers")
def layers(response: Response, case: str | None = Depends(get_case)):
    return respond(LAYERS, case, response)


@router.get("/gis/layers/{layer_id}")
def layer(
    layer_id: str,
    response: Response,
    scope: Scope = Depends(get_scope),
    timestep: int = 0,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    layer_id = LAYER_ALIASES.get(layer_id, layer_id)
    meta = next((x for x in LAYERS if x["id"] == layer_id), None)
    if not meta:
        raise HTTPException(404, f"Unknown layer {layer_id}")
    if not meta["available"]:
        # 409, not 404: the layer is real and registered, it just has no data source
        # yet. The UI shows a disabled toggle with the reason instead of a dead button.
        raise HTTPException(409, {"layer": layer_id, "reason": meta["source_hint"]})

    st, di = scope.state_code, scope.district_id

    if layer_id == "risk_heatmap":
        zones = db.scalars(services.apply_scope(select(RiskZone), RiskZone, st, di)).all()
        return respond(fc([{
            "type": "Feature",
            "geometry": z.geometry or {"type": "Point", "coordinates": [z.lng, z.lat]},
            "properties": {"id": z.id, "name": z.name, "risk_score": z.risk_score,
                           "risk_level": z.risk_level, "alert_tier": z.alert_tier,
                           "probability": z.probability, "district": z.district,
                           "sensor_confidence": z.sensor_confidence},
        } for z in zones]), case, response)

    if layer_id == "sensors":
        rows = db.scalars(services.apply_scope(select(Sensor), Sensor, st, di)).all()
        return respond(fc([point(s.lng, s.lat, {
            "id": s.id, "name": s.name, "type": s.sensor_type, "status": s.status,
            "health_score": s.health_score, "reading": s.reading, "unit": s.unit,
        }) for s in rows]), case, response)

    if layer_id == "roads":
        rows = db.scalars(services.apply_scope(select(Road), Road, st, di)).all()
        features = [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": r.path},
            "properties": {"id": r.id, "name": r.name, "status": r.status,
                           "risk_level": r.risk_level, "length_km": r.length_km,
                           "note": r.note, "source": "DISTRICT"},
        } for r in rows]
        # The corridor export carries surveyed NH-29 chainage sectors with traffic
        # and criticality attributes the district table does not have. Both are
        # shown; the corridor geometry is the more precise of the two.
        if _corridor_in_scope(st, di):
            for feat in gis_store.vector("roads").get("features", []):
                props = dict(feat.get("properties") or {})
                props.update({"id": props.get("asset_id"), "source": "GIS_CORRIDOR",
                              "status": props.get("status", "OPEN")})
                features.append({"type": "Feature", "geometry": feat["geometry"],
                                 "properties": props})
        return respond(fc(features), case, response)

    if layer_id == "spatial_risk":
        # The GIS pipeline's continuous risk grid, reduced to polygons the console can draw
        # without a tile server. Falls back to the zone polygons when the corridor
        # export is not present, so the layer is never an empty map.
        surface = gis_store.risk_polygons(timestep)
        if not surface["features"]:
            zones = db.scalars(services.apply_scope(select(RiskZone), RiskZone, st, di)).all()
            surface = fc([{
                "type": "Feature",
                "geometry": z.geometry or {"type": "Point", "coordinates": [z.lng, z.lat]},
                "properties": {"risk_score": z.risk_score, "risk_level": z.risk_level,
                               "source": "ZONE_MODEL"},
            } for z in zones])
        return respond(surface, case, response)

    if layer_id == "rivers":
        return respond(gis_store.vector("rivers"), case, response)

    if layer_id == "settlements":
        rows = db.scalars(services.apply_scope(select(Village), Village, st, di)).all()
        features = [point(v.lng, v.lat, {
            "id": v.id, "name": v.name, "population": v.population,
            "risk_level": v.risk_level, "connectivity": v.connectivity,
            "source": "DISTRICT",
        }) for v in rows]
        if _corridor_in_scope(st, di):
            for feat in gis_store.vector("settlements").get("features", []):
                props = dict(feat.get("properties") or {})
                props.update({"id": props.get("asset_id"), "source": "GIS_CORRIDOR"})
                features.append({"type": "Feature", "geometry": feat["geometry"],
                                 "properties": props})
        return respond(fc(features), case, response)

    if layer_id == "infrastructure":
        rows = db.scalars(
            services.apply_scope(select(Infrastructure), Infrastructure, st, di)).all()
        features = [point(i.lng, i.lat, {
            "id": i.id, "name": i.name, "type": i.infra_type,
            "importance": i.importance, "exposure": i.exposure,
            "population_served": i.population_served, "source": "DISTRICT",
        }) for i in rows]
        if _corridor_in_scope(st, di):
            for feat in gis_store.vector("critical_assets").get("features", []):
                props = dict(feat.get("properties") or {})
                props.update({"id": props.get("asset_id"),
                              "type": props.get("asset_type"), "source": "GIS_CORRIDOR"})
                features.append({"type": "Feature", "geometry": feat["geometry"],
                                 "properties": props})
        return respond(fc(features), case, response)

    if layer_id == "rainfall":
        zones = db.scalars(services.apply_scope(select(RiskZone), RiskZone, st, di)).all()
        return respond(fc([point(z.lng, z.lat, {
            "id": z.id, "rainfall_24h_mm": z.rainfall_24h_mm,
            "rainfall_72h_mm": z.rainfall_72h_mm,
            "soil_moisture_pct": z.soil_moisture_pct, "district": z.district,
        }) for z in zones]), case, response)

    if layer_id == "incidents":
        # Verified field reports and recorded events on one layer. An operator
        # asking "what has actually happened here" does not care which table it
        # came from; the `origin` property preserves the distinction for anyone
        # who does.
        features = []
        hist = db.scalars(
            services.apply_scope(select(HistoricalIncident), HistoricalIncident, st, di)
        ).all()
        for i in hist:
            features.append(point(i.lng, i.lat, {
                "id": i.id, "name": i.location, "incident_type": i.incident_type,
                "severity": i.severity, "date": i.date.isoformat() if i.date else None,
                "district": i.district, "affected_road": i.affected_road,
                "origin": "RECORDED_EVENT", "verification": "VERIFIED",
            }))
        reports = db.scalars(
            services.apply_scope(select(IncidentReport), IncidentReport, st, di)
        ).all()
        for r in reports:
            if r.verification == "REJECTED":
                continue
            features.append(point(r.lng, r.lat, {
                "id": r.id, "name": r.road_or_village or r.district,
                "incident_type": r.incident_type, "severity": r.severity,
                "date": r.reported_at.isoformat() if r.reported_at else None,
                "district": r.district, "reporter_type": r.reporter_type,
                "origin": "FIELD_REPORT", "verification": r.verification,
            }))
        return respond(fc(features), case, response)

    raise HTTPException(404, f"Layer {layer_id} has no server implementation")


def _dem_grid(district_id: str, amp: float, size: int = 16) -> list[list[float]]:
    """Procedural DEM stand-in.

    Explicitly synthetic and labelled as such in the response. Swap for real
    CartoDEM raster samples; the frontend reads `len(grid)`, not a hard-coded 16,
    so a 64x64 real grid drops straight in.
    """
    seed = sum(ord(c) for c in district_id)
    grid = []
    for y in range(size):
        row = []
        for x in range(size):
            a = math.sin(x / size * math.pi * 2.2) * 0.35
            b = math.cos(y / size * math.pi * 1.7) * 0.3
            c = math.sin((x + y + seed % 7) / size * math.pi * 1.3) * 0.22
            row.append(round(max(0.0, min(1.0, 0.5 + (a + b + c) * amp)), 3))
        grid.append(row)
    return grid


@router.get("/gis/terrain")
def terrain(
    response: Response,
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    did = scope.district_id if scope.district_id and scope.district_id != "ALL" else None
    d = DISTRICT_BY_ID.get(did) if did else None
    if d is None:
        d = DISTRICT_BY_ID["as-dima-hasao"]

    zones = db.scalars(select(RiskZone).where(RiskZone.district_id == d["id"])).all()
    w = TERRAIN_WEIGHT[d["terrain"]]
    elevs = [z.elevation_m for z in zones] or [400.0]
    slopes = [z.slope_deg for z in zones] or [20.0]
    aspects = [z.aspect_deg for z in zones] or [180.0]
    compass = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

    payload = {
        "district_id": d["id"],
        "district": d["name"],
        "elevation_min": round(min(elevs)),
        "elevation_max": round(max(elevs)),
        "elevation_mean": round(sum(elevs) / len(elevs)),
        "slope_mean": round(sum(slopes) / len(slopes), 1),
        "slope_max": round(max(slopes), 1),
        "aspect_dominant": compass[int((sum(aspects) / len(aspects)) // 45) % 8],
        "relief_m": round(max(elevs) - min(elevs)),
        "curvature_mean": round((w - 0.5) * 1.4, 2),
        "drainage_density": round(0.8 + w * 2.8, 2),
        "ruggedness_index": round(0.1 + w * 0.85, 2),
        "dem_grid": _dem_grid(d["id"], 0.55 + w * 0.75),
        "source": "MODEL_DERIVED",
        "note": "Terrain statistics derived from the zone model for this district.",
    }

    # Kohima is covered by the GIS module's surveyed DEM, so the real derivatives
    # replace the modelled ones for that district. Elsewhere the modelled profile
    # stands, and `source` says which one the reader is looking at.
    if d["id"] == gis_store.CORRIDOR_DISTRICT_ID and gis_store.available():
        md = gis_store.metadata()
        arrays = gis_store._terrain_arrays()
        if md and arrays is not None and "elevation" in arrays:
            slope_arr = arrays.get("slope_deg")
            tri = arrays.get("tri")
            twi = arrays.get("twi")
            streams = arrays.get("stream_network")
            payload.update({
                "elevation_min": round(md["min_elevation_m"]),
                "elevation_max": round(md["max_elevation_m"]),
                "elevation_mean": round(md["mean_elevation_m"]),
                "relief_m": round(md["max_elevation_m"] - md["min_elevation_m"]),
                "source": "GIS_DEM",
                "cell_size_m": md["cell_size_m"],
                "note": "Corridor DEM and derivatives from the GIS pipeline.",
            })
            if slope_arr is not None:
                payload["slope_mean"] = round(float(slope_arr.mean()), 1)
                payload["slope_max"] = round(float(slope_arr.max()), 1)
            if tri is not None:
                payload["ruggedness_index"] = round(float(tri.mean()), 2)
            if twi is not None:
                payload["wetness_index_mean"] = round(float(twi.mean()), 2)
            if streams is not None:
                payload["drainage_cells"] = int((streams > 0).sum())
    return respond(payload, case, response)


@router.get("/gis/infrastructure")
def gis_infrastructure(
    response: Response,
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    return respond(
        services.infrastructure_exposure(db, scope.state_code, scope.district_id),
        case, response,
    )


# --- plain asset lists ------------------------------------------------------ #
@router.get("/roads")
def roads(response: Response, scope: Scope = Depends(get_scope),
          db: Session = Depends(get_db), case: str | None = Depends(get_case)):
    rows = db.scalars(
        services.apply_scope(select(Road), Road, scope.state_code, scope.district_id)
    ).all()
    order = {"BLOCKED": 0, "RESTRICTED": 1, "AT_RISK": 2, "OPEN": 3}
    rows.sort(key=lambda r: order.get(r.status, 9))
    return respond([S.road(r) for r in rows], case, response)


@router.get("/villages")
def villages(response: Response, scope: Scope = Depends(get_scope),
             db: Session = Depends(get_db), case: str | None = Depends(get_case)):
    rows = db.scalars(
        services.apply_scope(select(Village), Village, scope.state_code, scope.district_id)
    ).all()
    return respond([S.village(v) for v in rows], case, response)


@router.get("/infrastructure")
def infrastructure(response: Response, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db), case: str | None = Depends(get_case)):
    rows = db.scalars(
        services.apply_scope(select(Infrastructure), Infrastructure,
                             scope.state_code, scope.district_id)
    ).all()
    return respond([S.infrastructure(i) for i in rows], case, response)


# --------------------------------------------------------------------------- #
# Corridor products
# --------------------------------------------------------------------------- #
@router.get("/gis/corridor")
def corridor(response: Response, timestep: int = 0,
             case: str | None = Depends(get_case)):
    """Headline corridor state: bounds, elevation range, exposure and the ranked
    priority list for the requested timestep."""
    return respond(gis_store.corridor_summary(timestep), case, response)


@router.get("/gis/exposure")
def exposure(response: Response, db: Session = Depends(get_db),
             scope: Scope = Depends(get_scope), timestep: int = 0,
             case: str | None = Depends(get_case)):
    """Exposure = risk x importance, answering "which asset gets the one crew?".

    The corridor's own prioritisation output is preferred where it exists, because
    it was computed against surveyed asset criticality; the district-level exposure
    model covers everywhere else.
    """
    corridor_reports = gis_store.exposure_timesteps()
    idx = max(0, min(len(corridor_reports) - 1, timestep)) if corridor_reports else 0
    payload = {
        "district_exposure": services.infrastructure_exposure(
            db, scope.state_code, scope.district_id),
        "corridor": corridor_reports[idx] if corridor_reports else None,
        "timesteps": [r.get("time_label") for r in corridor_reports],
        "source": "GIS exposure engine \u00b7 model-derived",
    }
    return respond(payload, case, response)


@router.get("/gis/context")
def spatial_context(
    response: Response,
    lat: float,
    lng: float,
    radius_km: float = 3.0,
    timestep: int = 0,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
):
    """Everything known about one point on the map.

    This is what a click on the map resolves to. A map that shows a coloured
    polygon and nothing else forces the operator to go and look the area up
    somewhere; this returns the risk, its inputs, the sensors reporting it and the
    assets standing in it, in one response.
    """
    zones = db.scalars(select(RiskZone)).all()
    nearest, best = None, 1e9
    for z in zones:
        d = math.hypot((z.lat - lat) * 111.32,
                       (z.lng - lng) * 111.32 * math.cos(math.radians(lat)))
        if d < best:
            nearest, best = z, d

    sensors = []
    if nearest is not None:
        sensors = db.scalars(select(Sensor).where(Sensor.zone_id == nearest.id)).all()

    payload = {
        "point": {"lat": lat, "lng": lng},
        "zone": S.risk_zone(nearest) if nearest else None,
        "distance_to_zone_km": round(best, 2) if nearest else None,
        # DEM-derived terrain, still doing its job with the map toggle gone.
        "terrain": gis_store.terrain_at(lat, lng),
        "spatial_risk": gis_store.spatial_risk_at(lat, lng, timestep),
        "sensors": {
            "total": len(sensors),
            "online": sum(1 for s in sensors if s.status == "ONLINE"),
            "degraded": sum(1 for s in sensors if s.status == "DEGRADED"),
            "offline": sum(1 for s in sensors if s.status == "OFFLINE"),
            "items": [S.sensor(s) for s in sensors],
        },
        "exposed_assets": gis_store.assets_near(lat, lng, radius_km),
    }
    return respond(payload, case, response)
