"""Corridor GIS store.

Reads the GIS module's exports (`data/gis/`) and serves them as operational map
layers. Nothing here re-derives what the GIS pipeline already computed: the DEM,
the seven terrain derivatives, the multi-temporal spatial risk grids and the
exposure/prioritisation reports are loaded as produced.

Two deliberate choices:

1. **DEM is loaded, not exposed as a toggle.** The console's layer picker does not
   offer a DEM/terrain raster — an operator does not need to look at elevation
   shading during an event. The elevation, slope, aspect, TRI and TWI grids are
   still read here and used for zone terrain context, the topographic section of
   the quarterly report, and the spatial-risk lookup. Removing the toggle is a UI
   decision; deleting the data would have been a capability regression.

2. **Loading is lazy and cached.** The corridor payload is ~800 kB of JSON. Parsing
   it on import would make `--reload` painful and would couple process start to a
   file that is optional in a stripped deployment. If the files are absent the
   store reports `available = False` and every endpoint degrades to the seeded
   district data rather than failing.
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger("ner.gis")

# The corridor these exports cover. Mapped onto the seeded district registry so the
# corridor layers appear under the district an operator already filters by.
CORRIDOR_DISTRICT_ID = "nl-kohima"
CORRIDOR_NAME = "Kohima\u2013Dimapur (NH-29) Corridor"

_VECTOR_FILES = {
    "roads": "vector/roads.geojson",
    "settlements": "vector/settlements.geojson",
    "rivers": "vector/rivers.geojson",
    "critical_assets": "vector/critical_assets.geojson",
    "sensors": "vector/sensor_network.geojson",
    # Live open-source & Indian Government data feeds (GIS Intelligence page).
    "seismic": "live/seismic_triggers.geojson",
    "soil_moisture": "live/soil_moisture_telemetry.geojson",
    "gsi_susceptibility": "live/gsi_nlsm_susceptibility.geojson",
    "osm_infrastructure": "live/osm_infrastructure.geojson",
}


def _root() -> Path:
    return Path(settings.gis_data_dir)


@lru_cache(maxsize=1)
def available() -> bool:
    root = _root()
    ok = root.is_dir() and (root / "vector" / "roads.geojson").is_file()
    if not ok:
        log.warning("GIS corridor data not found under %s \u2014 serving district data only", root)
    return ok


@lru_cache(maxsize=1)
def metadata() -> dict:
    """Grid bounds and elevation range for the corridor raster."""
    path = _root() / "dem" / "dem_metadata.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


@lru_cache(maxsize=8)
def vector(name: str) -> dict:
    """One GeoJSON FeatureCollection from the GIS export, or an empty one."""
    rel = _VECTOR_FILES.get(name)
    if not rel:
        return {"type": "FeatureCollection", "features": []}
    path = _root() / rel
    if not path.is_file():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def live_summary() -> dict:
    """Live open-data and Indian government telemetry summary."""
    path = _root() / "live" / "live_telemetry_summary.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def exposure_timesteps() -> list[dict]:
    """Ranked exposure / prioritisation report per simulated timestep."""
    path = _root() / "risk" / "exposure_summary_all_timesteps.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else []


@lru_cache(maxsize=1)
def _terrain_arrays() -> dict[str, Any]:
    """DEM derivatives. Requires numpy; absent numpy is not fatal."""
    path = _root() / "dem" / "kohima_terrain_derivatives.npz"
    if not path.is_file():
        return {}
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is in requirements
        return {}
    with np.load(path, allow_pickle=True) as z:
        return {k: z[k] for k in z.files if k != "metadata"}


@lru_cache(maxsize=1)
def _risk_grids() -> list[tuple[str, Any]]:
    """Multi-temporal spatial risk grids, ordered as the pipeline wrote them."""
    path = _root() / "risk" / "spatial_risk_timesteps.npz"
    if not path.is_file():
        return []
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return []
    with np.load(path) as z:
        keys = list(z.files)
        return [(k.replace("risk_", ""), z[k]) for k in keys]


def timestep_labels() -> list[str]:
    return [label for label, _ in _risk_grids()]


# --------------------------------------------------------------------------- #
# Grid <-> lat/lng
# --------------------------------------------------------------------------- #
def _cell_for(lat: float, lng: float) -> tuple[int, int] | None:
    md = metadata()
    if not md:
        return None
    rows, cols = int(md["rows"]), int(md["cols"])
    if not (md["min_lat"] <= lat <= md["max_lat"] and md["min_lon"] <= lng <= md["max_lon"]):
        return None
    fx = (lng - md["min_lon"]) / (md["max_lon"] - md["min_lon"])
    fy = (md["max_lat"] - lat) / (md["max_lat"] - md["min_lat"])   # row 0 = north
    return min(rows - 1, int(fy * rows)), min(cols - 1, int(fx * cols))


def terrain_at(lat: float, lng: float) -> dict | None:
    """DEM-derived terrain at a point. This is the DEM still doing its job after the
    UI toggle was removed."""
    cell = _cell_for(lat, lng)
    arrays = _terrain_arrays()
    if cell is None or not arrays:
        return None
    r, c = cell
    out = {}
    for key in ("elevation", "slope_deg", "aspect_deg", "tri", "twi",
                "profile_curvature", "planform_curvature"):
        arr = arrays.get(key)
        if arr is not None:
            out[key] = round(float(arr[r][c]), 3)
    return out or None


def spatial_risk_at(lat: float, lng: float, timestep: int = 0) -> float | None:
    grids = _risk_grids()
    cell = _cell_for(lat, lng)
    if cell is None or not grids:
        return None
    idx = max(0, min(len(grids) - 1, timestep))
    r, c = cell
    return round(float(grids[idx][1][r][c]), 1)


# --------------------------------------------------------------------------- #
# Derived operational products
# --------------------------------------------------------------------------- #
def risk_polygons(timestep: int = 0, bands: int = 4, coarse: int = 20) -> dict:
    """Spatial risk raster reduced to a polygon FeatureCollection.

    Leaflet-free rendering is a hard requirement for this console (no map tile
    provider, no external network in a district office), so the risk surface is
    delivered as coarse polygons the SVG map can draw directly rather than as a
    raster the client would have to georeference itself. `coarse` blocks of cells
    are averaged, which also keeps the payload small enough for a metered link.
    """
    grids = _risk_grids()
    md = metadata()
    if not grids or not md:
        return {"type": "FeatureCollection", "features": []}

    idx = max(0, min(len(grids) - 1, timestep))
    label, grid = grids[idx]
    rows, cols = len(grid), len(grid[0])
    step_r, step_c = max(1, rows // coarse), max(1, cols // coarse)
    lat_span = md["max_lat"] - md["min_lat"]
    lng_span = md["max_lon"] - md["min_lon"]

    features = []
    for r0 in range(0, rows, step_r):
        for c0 in range(0, cols, step_c):
            block = [float(grid[r][c])
                     for r in range(r0, min(r0 + step_r, rows))
                     for c in range(c0, min(c0 + step_c, cols))]
            if not block:
                continue
            mean = sum(block) / len(block)
            level = _band(mean, bands)
            if level == "LOW":
                continue                     # do not ship the quiet 60% of the grid
            north = md["max_lat"] - (r0 / rows) * lat_span
            south = md["max_lat"] - (min(r0 + step_r, rows) / rows) * lat_span
            west = md["min_lon"] + (c0 / cols) * lng_span
            east = md["min_lon"] + (min(c0 + step_c, cols) / cols) * lng_span
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[
                    [west, north], [east, north], [east, south], [west, south], [west, north],
                ]]},
                "properties": {
                    "risk_score": round(mean, 1),
                    "risk_level": level,
                    "timestep": label,
                    "source": "GIS_SPATIAL_RISK",
                },
            })
    return {"type": "FeatureCollection", "features": features,
            "properties": {"timestep": label, "timestep_index": idx,
                            "timesteps": timestep_labels()}}


def _band(score: float, bands: int = 4) -> str:
    b = settings.bands
    if score >= b.critical:
        return "CRITICAL"
    if score >= b.high:
        return "HIGH"
    if score >= b.moderate:
        return "MODERATE"
    return "LOW"


def corridor_summary(timestep: int = 0) -> dict:
    """Headline numbers for the corridor at one timestep."""
    reports = exposure_timesteps()
    md = metadata()
    grids = _risk_grids()
    idx = max(0, min(len(reports) - 1, timestep)) if reports else 0
    rep = reports[idx] if reports else {}

    mean_risk = max_risk = None
    if grids:
        gi = max(0, min(len(grids) - 1, timestep))
        grid = grids[gi][1]
        flat = [float(v) for row in grid for v in row]
        mean_risk = round(sum(flat) / len(flat), 1)
        max_risk = round(max(flat), 1)

    return {
        "name": CORRIDOR_NAME,
        "district_id": CORRIDOR_DISTRICT_ID,
        "available": available(),
        "bounds": [md.get("min_lon"), md.get("min_lat"), md.get("max_lon"), md.get("max_lat")]
        if md else None,
        "cell_size_m": md.get("cell_size_m"),
        "elevation_min_m": md.get("min_elevation_m"),
        "elevation_max_m": md.get("max_elevation_m"),
        "elevation_mean_m": round(md["mean_elevation_m"], 1) if md.get("mean_elevation_m") else None,
        "timestep": rep.get("time_label") or (grids[timestep][0] if grids else None),
        "timestep_index": idx,
        "timesteps": [r.get("time_label") for r in reports] or timestep_labels(),
        "mean_risk": mean_risk,
        "max_risk": max_risk,
        "scenario": rep.get("monsoon_scenario"),
        "exposed_road_km": rep.get("total_exposed_road_km"),
        "threatened_population": rep.get("threatened_population"),
        "critical_assets_at_risk": rep.get("critical_assets_at_risk_count"),
        "evacuation_alert_level": rep.get("evacuation_alert_level"),
        "priority_assets": (rep.get("ranked_priority_list") or [])[:8],
        "counts": {k: len(vector(k).get("features", [])) for k in _VECTOR_FILES},
        "source": "GIS pipeline export \u00b7 model-derived",
    }


def _distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    dlat = (b_lat - a_lat) * 111.32
    dlng = (b_lng - a_lng) * 111.32 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dlat, dlng)


def _feature_point(feat: dict) -> tuple[float, float] | None:
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords:
        return None
    if geom.get("type") == "Point":
        return coords[1], coords[0]
    if geom.get("type") == "LineString":
        mid = coords[len(coords) // 2]
        return mid[1], mid[0]
    return None


def assets_near(lat: float, lng: float, radius_km: float = 3.0) -> list[dict]:
    """Every corridor asset within `radius_km` — what is exposed at this point."""
    out: list[dict] = []
    for kind in ("roads", "settlements", "critical_assets", "rivers"):
        for feat in vector(kind).get("features", []):
            pt = _feature_point(feat)
            if pt is None:
                continue
            d = _distance_km(lat, lng, pt[0], pt[1])
            if d > radius_km:
                continue
            props = feat.get("properties", {})
            out.append({
                "layer": kind,
                "id": props.get("asset_id") or props.get("river_id") or props.get("sensor_id"),
                "name": props.get("name", "Unnamed"),
                "type": props.get("asset_type") or props.get("road_type") or props.get("type"),
                "population": props.get("population"),
                "criticality_weight": props.get("criticality_weight"),
                "distance_km": round(d, 2),
            })
    return sorted(out, key=lambda a: a["distance_km"])
