"""
Canonical Data Schema
=====================

Purpose
-------
Defines the field contract shared by every module in the pipeline: historical
ingestion, sensor streams, physics simulation and ML training all read and
write these schemas. New data sources are integrated by writing a loader that
maps into this schema (see historical_ingestion.py), never by changing the
schema itself.

Record types
------------
1. HISTORICAL_EVENT_SCHEMA: one row per reported landslide or confirmed
   non-event control point, used for training and validation.
2. SENSOR_READING_SCHEMA: one row per sensor reading, used for live
   monitoring, sensor-health scoring and real-time inference.

Notes
-----
Field naming mirrors the backend service data model for zones and sensors,
and the fields required by the DEM layer (latitude, longitude, elevation,
slope), so that no translation layer is needed between components.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Historical / inventory event schema
# ---------------------------------------------------------------------------
HISTORICAL_EVENT_SCHEMA = {
    "event_id":            "str    - unique id (source-prefixed, e.g. 'GLC_00123', 'GSI_BHUKOSH_00456')",
    "source":               "str    - 'NASA_COOLR' | 'GSI_BHUKOSH' | 'BHUVAN_NRSC' | 'STATE_DMA' | 'SYNTHETIC_NER'",
    "date":                 "date   - event date (or observation date for a negative/control point), ISO 8601",
    "state":                "str    - NER state: Assam | Meghalaya | Mizoram | Manipur | Nagaland | Tripura | Sikkim | Arunachal Pradesh",
    "district":             "str",
    "latitude":             "float  - WGS84",
    "longitude":            "float  - WGS84",
    "elevation_m":          "float  - metres above sea level",
    "slope_deg":            "float  - local slope angle in degrees (from DEM, provided by the GIS layer once available)",
    "aspect_deg":           "float  - slope aspect, 0-360, optional",
    "landcover":            "str    - 'forest' | 'cropland' | 'built-up' | 'bare' | 'grassland' | 'unknown'",
    "soil_type":            "str    - dominant soil/geology class where known, else 'unknown'",
    "rainfall_24h_mm":      "float  - rainfall in 24h preceding the date (IMD gridded / station)",
    "rainfall_72h_mm":      "float  - rainfall in preceding 72h",
    "rainfall_7d_mm":       "float  - rainfall in preceding 7 days",
    "antecedent_precip_index": "float - API, exponentially-weighted rainfall memory (see feature_engineering)",
    "soil_moisture_pct":    "float  - volumetric soil moisture at time of event, if available (satellite/sensor)",
    "landslide_occurred":   "int    - 1 = confirmed landslide, 0 = confirmed non-event / control point",
    "landslide_type":       "str    - 'debris flow' | 'rock slide' | 'soil slide' | 'mudslide' | 'unknown', optional",
    "fatalities":           "int    - optional, for severity weighting in the reporting layer",
    "data_confidence":      "str    - 'high' (field-verified) | 'medium' (media/report) | 'low' (inferred), used in QA weighting",
}

# ---------------------------------------------------------------------------
# 2. Live sensor reading schema
# ---------------------------------------------------------------------------
SENSOR_READING_SCHEMA = {
    "sensor_id":            "str    - matches BackEnd.db.models.Sensor.id",
    "zone_id":               "str    - matches Zone.id",
    "sensor_type":           "str    - 'rain_gauge' | 'soil_moisture' | 'piezometer' | 'tiltmeter' | 'extensometer' | 'geophone'",
    "timestamp":             "datetime - UTC, ISO 8601",
    "value":                 "float  - raw reading in the sensor's native unit",
    "unit":                  "str    - 'mm' | 'pct' | 'kPa' | 'deg' | 'mm/hr' etc.",
    "battery_pct":           "float  - optional, feeds into sensor-health score",
    "rssi_dbm":               "float  - optional signal strength, feeds into comms-health",
    "expected_interval_s":  "int    - expected reporting cadence for this sensor type, used for gap/comms-failure detection",
}


@dataclass
class NERRegionBounds:
    """Rough bounding box + elevation/rainfall priors for the eight NER states.
    Used to keep synthetic/placeholder data physically plausible and to
    sanity-check ingested records (a 'landslide at sea level with 50mm
    annual rainfall' is a data-quality flag, not a real NER event).
    """
    lat_min: float = 21.5
    lat_max: float = 29.5
    lon_min: float = 88.0
    lon_max: float = 97.5
    elevation_min_m: float = 20.0
    elevation_max_m: float = 5000.0     # Kangchenjunga massif, Sikkim
    monsoon_annual_rainfall_min_mm: float = 1200.0
    monsoon_annual_rainfall_max_mm: float = 11000.0  # Cherrapunji/Mawsynram, Meghalaya
    states: tuple = field(default_factory=lambda: (
        "Assam", "Meghalaya", "Mizoram", "Manipur",
        "Nagaland", "Tripura", "Sikkim", "Arunachal Pradesh",
    ))


def print_schema():
    print("HISTORICAL_EVENT_SCHEMA")
    print("-" * 70)
    for k, v in HISTORICAL_EVENT_SCHEMA.items():
        print(f"  {k:28s} {v}")
    print("\nSENSOR_READING_SCHEMA")
    print("-" * 70)
    for k, v in SENSOR_READING_SCHEMA.items():
        print(f"  {k:28s} {v}")


if __name__ == "__main__":
    print_schema()
