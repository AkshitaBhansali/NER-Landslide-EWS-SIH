"""
Historical Landslide Dataset Assembly
=====================================

Purpose
-------
Assembles historical landslide records for the North Eastern Region from
government, geological, satellite and open-data sources, and normalises them
onto HISTORICAL_EVENT_SCHEMA (see schema.py).

Contents
--------
1. REAL_SOURCES: registry of the production data sources with URL, access
   method, native field names and confidence level.
2. One `load_*` function per source, mapping the native columns of that source
   onto HISTORICAL_EVENT_SCHEMA. Column mappings follow each published source
   schema and are ready to run against a real export.
3. `generate_placeholder_ner_dataset()`: a synthetic, NER-scoped stand-in
   dataset used while manual exports are pending. Every row carries
   source == 'SYNTHETIC_NER' and data_confidence == 'low', so placeholder
   data cannot be mistaken for observed history downstream.

The placeholder generator exists because the portals listed below require a
manual area-of-interest export through a web application and expose no bulk
download API.

Sources
-------
- NASA COOLR / Global Landslide Catalog: more than 11,000 rainfall-triggered
  events worldwide from 2007 onwards, media-sourced and citizen-sourced.
  Export via the Landslide Viewer ArcGIS application as CSV, shapefile or
  geodatabase.
  https://landslides.nasa.gov
  https://catalog.data.gov/dataset/global-landslide-catalog-export
- GSI Bhukosh: Geological Survey of India open geoscience portal, including
  the National Landslide Susceptibility Mapping layers at 1:50,000 scale
  covering roughly 4.3 lakh sq km, and district landslide inventories.
  https://bhukosh.gsi.gov.in
- GSI Bhusanket portal and Bhooskhalan application, operated by the National
  Landslide Forecasting Centre in Kolkata: forecast bulletins and historical
  event logs for covered districts, including Kohima since the 2025 monsoon.
  https://bhusanket.gsi.gov.in
- Bhuvan (ISRO/NRSC): susceptibility layers and satellite-derived terrain and
  land-cover products for DEM cross-referencing. https://bhuvan.nrsc.gov.in
- IMD gridded rainfall: daily and hourly gridded rainfall used to construct
  rainfall_24h_mm, rainfall_72h_mm, rainfall_7d_mm and the antecedent
  precipitation index. https://imdpune.gov.in
- State Disaster Management Authorities and DesInventar (desinventar.net) for
  state-level disaster-loss records feeding the impact and fatality fields.

See research/historical_data_sources.md for the full source survey and the
native-to-canonical field mapping table.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import date, timedelta

from schema import HISTORICAL_EVENT_SCHEMA, NERRegionBounds


REAL_SOURCES = {
    "NASA_COOLR": {
        "url": "https://catalog.data.gov/dataset/global-landslide-catalog-export",
        "format": "CSV / SHP / GDB (export from ArcGIS Landslide Viewer)",
        "native_key_columns": ["event_date", "event_time", "latitude", "longitude",
                                "landslide_category", "landslide_trigger", "fatality_count"],
        "notes": "Global; filter to NER bounding box after download. Media/citizen-"
                 "sourced so treat as data_confidence='medium'.",
    },
    "GSI_BHUKOSH": {
        "url": "https://bhukosh.gsi.gov.in",
        "format": "WebGIS layers, manual AOI export (shapefile/geojson)",
        "native_key_columns": ["LAT", "LONG", "STATE", "DISTRICT", "LITHOLOGY", "SLOPE_CAT"],
        "notes": "Authoritative for India; NLSM covers the NE Tertiary belt at 1:50,000. "
                 "data_confidence='high'.",
    },
    "GSI_BHUSANKET_NLFC": {
        "url": "https://bhusanket.gsi.gov.in",
        "format": "Portal / Bhooskhalan app export",
        "native_key_columns": ["district", "forecast_date", "rainfall_threshold_exceeded", "advisory_level"],
        "notes": "Kohima (Nagaland) is live as of the 2025 monsoon - directly relevant to "
                 "NER; worth requesting a data-sharing MoU as a project partner reference.",
    },
    "BHUVAN_NRSC": {
        "url": "https://bhuvan.nrsc.gov.in",
        "format": "WMS/WFS thematic services, DEM (CartoDEM)",
        "native_key_columns": ["susceptibility_class", "landcover_class"],
        "notes": "Primarily for terrain/land-cover cross-referencing rather than event points.",
    },
}


def load_generic_csv(path: str, column_mapping: dict, source_name: str) -> pd.DataFrame:
    """
    Generic loader: point at any exported CSV plus a dict mapping
    {native_column_name: schema_field_name}, and it normalizes into
    HISTORICAL_EVENT_SCHEMA. This is the function to call once a real
    NASA_COOLR / GSI_BHUKOSH export lands on disk - no rewrite needed.
    """
    raw = pd.read_csv(path)
    df = raw.rename(columns=column_mapping)
    missing = [c for c in HISTORICAL_EVENT_SCHEMA if c not in df.columns]
    for c in missing:
        df[c] = np.nan
    df["source"] = source_name
    return df[list(HISTORICAL_EVENT_SCHEMA.keys())]


def load_nasa_coolr(path: str) -> pd.DataFrame:
    """Ready-to-use mapping for a NASA COOLR/GLC CSV export."""
    mapping = {
        "event_id": "event_id", "event_date": "date",
        "latitude": "latitude", "longitude": "longitude",
        "landslide_category": "landslide_type",
        "fatality_count": "fatalities",
        "admin_division_name": "state",
    }
    df = load_generic_csv(path, mapping, "NASA_COOLR")
    df["landslide_occurred"] = 1  # GLC only logs confirmed events
    df["data_confidence"] = "medium"
    return df


def load_gsi_bhukosh(path: str) -> pd.DataFrame:
    """Ready-to-use mapping for a GSI Bhukosh AOI export."""
    mapping = {
        "LAT": "latitude", "LONG": "longitude", "STATE": "state",
        "DISTRICT": "district", "LITHOLOGY": "soil_type",
    }
    df = load_generic_csv(path, mapping, "GSI_BHUKOSH")
    df["data_confidence"] = "high"
    return df


# ---------------------------------------------------------------------------
# Placeholder dataset: synthetic, NER-scoped, tagged as low confidence
# ---------------------------------------------------------------------------
def generate_placeholder_ner_dataset(n_events: int = 1200, n_negatives: int = 2400,
                                      seed: int = 42) -> pd.DataFrame:
    """
    Generates a NER-scoped placeholder historical dataset. NOT real data -
    every row is tagged source='SYNTHETIC_NER', data_confidence='low'.

    Statistics used to keep it physically plausible are drawn from published
    figures (not fabricated numbers dressed as facts):
      - NER receives among the highest rainfall in the world; Meghalaya
        (Mawsynram/Cherrapunji) tops 10,000+ mm/yr, while rain-shadow parts
        of Manipur/Nagaland are much drier - reflected in state-level
        rainfall priors below.
      - GSI's National Landslide Susceptibility Mapping places most of NER's
        landslide-prone terrain in hilly/steep terrain (slope 25-45 deg
        typical failure range for shallow soil slides, per infinite-slope
        literature used in simulation/physics_slope_model.py).
      - Monsoon (Jun-Sep) concentration of events, consistent with GSI/IMD
        reporting that the large majority of NER landslides are rainfall-
        triggered during monsoon months.

    Replace this function's output with a `load_*` call the moment a real
    export is available - the schema is identical so nothing downstream
    needs to change.
    """
    rng = np.random.default_rng(seed)
    bounds = NERRegionBounds()

    # Rough per-state rainfall/elevation priors (mm/yr, m) - order matches bounds.states
    state_priors = {
        "Assam":             dict(rain=(1800, 3200), elev=(30, 600)),
        "Meghalaya":         dict(rain=(4000, 11000), elev=(150, 1950)),
        "Mizoram":           dict(rain=(2200, 3000), elev=(100, 2150)),
        "Manipur":           dict(rain=(1200, 2200), elev=(750, 2900)),
        "Nagaland":          dict(rain=(1800, 2600), elev=(200, 3800)),
        "Tripura":           dict(rain=(2000, 2600), elev=(30, 950)),
        "Sikkim":            dict(rain=(1500, 4000), elev=(300, 5000)),
        "Arunachal Pradesh": dict(rain=(2000, 4500), elev=(100, 5000)),
    }

    def sample_rows(n, occurred_flag):
        states = rng.choice(list(state_priors.keys()), size=n)
        rows = []
        for i in range(n):
            st = states[i]
            p = state_priors[st]
            elevation = rng.uniform(*p["elev"])
            annual_rain = rng.uniform(*p["rain"])

            # Monsoon-weighted event dates (Jun-Sep heavier)
            if rng.random() < 0.72:
                month = rng.integers(6, 10)
            else:
                month = rng.integers(1, 13)
            day = int(rng.integers(1, 28))
            year = int(rng.integers(2015, 2026))
            try:
                event_date = date(year, int(month), day)
            except ValueError:
                event_date = date(year, int(month), 1)

            # Landslide-triggering slopes cluster 25-45deg (shallow soil slide range);
            # negatives skew toward gentler or very rocky/steep-stable terrain.
            if occurred_flag:
                slope = float(np.clip(rng.normal(34, 7), 12, 65))
                rain_multiplier = rng.uniform(1.3, 2.6)  # anomalously wet spell
            else:
                slope = float(np.clip(rng.normal(22, 10), 2, 65))
                rain_multiplier = rng.uniform(0.4, 1.1)

            daily_avg = annual_rain / 365.0
            rainfall_24h = max(0.0, rng.normal(daily_avg * rain_multiplier * 3, daily_avg))
            rainfall_72h = rainfall_24h * rng.uniform(1.8, 3.2)
            rainfall_7d = rainfall_72h * rng.uniform(1.4, 2.2)
            api = rainfall_7d * 0.5 + rainfall_72h * 0.3 + rainfall_24h * 0.2

            rows.append(dict(
                event_id=f"SYN_{'E' if occurred_flag else 'N'}_{i:05d}",
                source="SYNTHETIC_NER",
                date=event_date.isoformat(),
                state=st,
                district="unspecified",
                latitude=round(rng.uniform(bounds.lat_min, bounds.lat_max), 5),
                longitude=round(rng.uniform(bounds.lon_min, bounds.lon_max), 5),
                elevation_m=round(elevation, 1),
                slope_deg=round(slope, 2),
                aspect_deg=round(float(rng.uniform(0, 360)), 1),
                landcover=rng.choice(["forest", "cropland", "grassland", "bare", "built-up"],
                                      p=[0.5, 0.2, 0.15, 0.1, 0.05]),
                soil_type=rng.choice(["residual_soil", "colluvium", "weathered_rock", "unknown"],
                                      p=[0.4, 0.3, 0.2, 0.1]),
                rainfall_24h_mm=round(rainfall_24h, 1),
                rainfall_72h_mm=round(rainfall_72h, 1),
                rainfall_7d_mm=round(rainfall_7d, 1),
                antecedent_precip_index=round(api, 1),
                soil_moisture_pct=round(float(np.clip(rng.normal(38 if occurred_flag else 24, 8), 5, 95)), 1),
                landslide_occurred=int(occurred_flag),
                landslide_type=(rng.choice(["debris flow", "soil slide", "mudslide", "rock slide"],
                                            p=[0.35, 0.35, 0.2, 0.1]) if occurred_flag else "n/a"),
                fatalities=(int(rng.poisson(0.6)) if occurred_flag and rng.random() < 0.15 else 0),
                data_confidence="low",
            ))
        return rows

    events = sample_rows(n_events, True)
    negatives = sample_rows(n_negatives, False)
    df = pd.DataFrame(events + negatives)
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return df[list(HISTORICAL_EVENT_SCHEMA.keys())]


if __name__ == "__main__":
    print("Real source registry:")
    for name, meta in REAL_SOURCES.items():
        print(f"  - {name}: {meta['url']}")

    df = generate_placeholder_ner_dataset()
    out_path = "../data/historical_events_placeholder.csv"
    df.to_csv(out_path, index=False)
    print(f"\nPlaceholder dataset generated: {df.shape[0]} rows -> {out_path}")
    print(df["state"].value_counts())
    print(f"\nEvent rate: {df['landslide_occurred'].mean():.2%}")
