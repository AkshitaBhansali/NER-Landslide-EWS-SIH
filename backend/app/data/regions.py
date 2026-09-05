"""Canonical NER region registry.

Extracted from the frontend bundle so district IDs, centroids, terrain classes and
populations are identical on both sides. These IDs are the join key for every table.
"""
from __future__ import annotations

STATES = [
    {"code": "AS", "name": "Assam", "center": {"lat": 26.2, "lng": 92.9}},
    {"code": "AR", "name": "Arunachal Pradesh", "center": {"lat": 28, "lng": 94.7}},
    {"code": "MN", "name": "Manipur", "center": {"lat": 24.7, "lng": 93.9}},
    {"code": "ML", "name": "Meghalaya", "center": {"lat": 25.5, "lng": 91.4}},
    {"code": "MZ", "name": "Mizoram", "center": {"lat": 23.4, "lng": 92.8}},
    {"code": "NL", "name": "Nagaland", "center": {"lat": 26.1, "lng": 94.4}},
    {"code": "SK", "name": "Sikkim", "center": {"lat": 27.5, "lng": 88.5}},
    {"code": "TR", "name": "Tripura", "center": {"lat": 23.8, "lng": 91.6}},
]

DISTRICTS = [
    {"id": "as-dima-hasao", "name": "Dima Hasao", "state_code": "AS", "lat": 25.35, "lng": 93.03, "population": 214102, "terrain": "STEEP_HILL"},
    {"id": "as-karbi-anglong", "name": "Karbi Anglong", "state_code": "AS", "lat": 25.95, "lng": 93.42, "population": 660955, "terrain": "HILL"},
    {"id": "as-cachar", "name": "Cachar", "state_code": "AS", "lat": 24.83, "lng": 92.78, "population": 1736617, "terrain": "VALLEY"},
    {"id": "as-hailakandi", "name": "Hailakandi", "state_code": "AS", "lat": 24.68, "lng": 92.56, "population": 659296, "terrain": "VALLEY"},
    {"id": "as-kamrup-metro", "name": "Kamrup Metropolitan", "state_code": "AS", "lat": 26.14, "lng": 91.74, "population": 1253938, "terrain": "PLAIN"},
    {"id": "as-goalpara", "name": "Goalpara", "state_code": "AS", "lat": 26.17, "lng": 90.62, "population": 1008183, "terrain": "PLAIN"},
    {"id": "ar-tawang", "name": "Tawang", "state_code": "AR", "lat": 27.59, "lng": 91.87, "population": 49977, "terrain": "STEEP_HILL"},
    {"id": "ar-papum-pare", "name": "Papum Pare", "state_code": "AR", "lat": 27.1, "lng": 93.62, "population": 176573, "terrain": "HILL"},
    {"id": "ar-lower-subansiri", "name": "Lower Subansiri", "state_code": "AR", "lat": 27.62, "lng": 93.83, "population": 83030, "terrain": "STEEP_HILL"},
    {"id": "ar-dibang-valley", "name": "Dibang Valley", "state_code": "AR", "lat": 28.65, "lng": 95.9, "population": 8004, "terrain": "STEEP_HILL"},
    {"id": "mn-imphal-west", "name": "Imphal West", "state_code": "MN", "lat": 24.81, "lng": 93.9, "population": 517992, "terrain": "VALLEY"},
    {"id": "mn-churachandpur", "name": "Churachandpur", "state_code": "MN", "lat": 24.33, "lng": 93.68, "population": 271274, "terrain": "HILL"},
    {"id": "mn-senapati", "name": "Senapati", "state_code": "MN", "lat": 25.27, "lng": 94.02, "population": 354772, "terrain": "STEEP_HILL"},
    {"id": "mn-noney", "name": "Noney", "state_code": "MN", "lat": 24.83, "lng": 93.53, "population": 47217, "terrain": "STEEP_HILL"},
    {"id": "ml-east-khasi-hills", "name": "East Khasi Hills", "state_code": "ML", "lat": 25.57, "lng": 91.88, "population": 825922, "terrain": "PLATEAU"},
    {"id": "ml-ri-bhoi", "name": "Ri-Bhoi", "state_code": "ML", "lat": 25.9, "lng": 91.88, "population": 258840, "terrain": "HILL"},
    {"id": "ml-west-jaintia-hills", "name": "West Jaintia Hills", "state_code": "ML", "lat": 25.45, "lng": 92.2, "population": 270352, "terrain": "PLATEAU"},
    {"id": "ml-south-garo-hills", "name": "South Garo Hills", "state_code": "ML", "lat": 25.32, "lng": 90.62, "population": 142334, "terrain": "HILL"},
    {"id": "mz-aizawl", "name": "Aizawl", "state_code": "MZ", "lat": 23.73, "lng": 92.72, "population": 400309, "terrain": "STEEP_HILL"},
    {"id": "mz-lunglei", "name": "Lunglei", "state_code": "MZ", "lat": 22.88, "lng": 92.73, "population": 161428, "terrain": "STEEP_HILL"},
    {"id": "mz-serchhip", "name": "Serchhip", "state_code": "MZ", "lat": 23.3, "lng": 92.85, "population": 64937, "terrain": "HILL"},
    {"id": "nl-kohima", "name": "Kohima", "state_code": "NL", "lat": 25.67, "lng": 94.11, "population": 267988, "terrain": "STEEP_HILL"},
    {"id": "nl-dimapur", "name": "Dimapur", "state_code": "NL", "lat": 25.9, "lng": 93.73, "population": 378811, "terrain": "PLAIN"},
    {"id": "nl-phek", "name": "Phek", "state_code": "NL", "lat": 25.67, "lng": 94.47, "population": 163418, "terrain": "HILL"},
    {"id": "sk-gangtok", "name": "Gangtok", "state_code": "SK", "lat": 27.33, "lng": 88.61, "population": 283583, "terrain": "STEEP_HILL"},
    {"id": "sk-mangan", "name": "Mangan", "state_code": "SK", "lat": 27.51, "lng": 88.53, "population": 43709, "terrain": "STEEP_HILL"},
    {"id": "sk-namchi", "name": "Namchi", "state_code": "SK", "lat": 27.17, "lng": 88.36, "population": 146742, "terrain": "HILL"},
    {"id": "tr-west-tripura", "name": "West Tripura", "state_code": "TR", "lat": 23.84, "lng": 91.28, "population": 917534, "terrain": "PLAIN"},
    {"id": "tr-dhalai", "name": "Dhalai", "state_code": "TR", "lat": 23.93, "lng": 91.83, "population": 378230, "terrain": "HILL"},
    {"id": "tr-south-tripura", "name": "South Tripura", "state_code": "TR", "lat": 23.31, "lng": 91.48, "population": 430751, "terrain": "HILL"},
]


# Terrain class -> ruggedness multiplier (mirrors TERRAIN_WEIGHT in the frontend generator)
TERRAIN_WEIGHT = {"STEEP_HILL": 1.0, "HILL": 0.78, "PLATEAU": 0.62, "VALLEY": 0.45, "PLAIN": 0.2}

STATE_BY_CODE = {s["code"]: s for s in STATES}
DISTRICT_BY_ID = {d["id"]: d for d in DISTRICTS}


def districts_in_scope(state_code: str | None = None, district_id: str | None = None):
    """Scope filter shared by every list endpoint. district_id wins over state_code."""
    if district_id and district_id != "ALL":
        d = DISTRICT_BY_ID.get(district_id)
        return [d] if d else []
    if state_code and state_code != "ALL":
        return [d for d in DISTRICTS if d["state_code"] == state_code]
    return list(DISTRICTS)
