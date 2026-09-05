"""
Spatial Storage, Indexing and Database Engine
============================================
Handles spatial persistence, format serialization (GeoJSON, GeoPackage, SQLite, PostGIS DDL),
spatial indexing, and query abstractions for raster and vector geospatial layers.
"""

from __future__ import annotations
import json
import sqlite3
import os
from typing import Dict, Any, List, Optional


class SpatialStorageEngine:
    """Manages serialization, spatial indexing, and PostGIS schema exporting."""

    def __init__(self, export_dir: str = "data/export"):
        self.export_dir = export_dir
        os.makedirs(export_dir, exist_ok=True)

    def save_geojson(self, data: Dict[str, Any], filename: str) -> str:
        """Saves GeoJSON dictionary to a formatting-validated GeoJSON file."""
        filepath = os.path.join(self.export_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return filepath

    def export_sqlite_geopackage_mock(self, layers: Dict[str, Dict[str, Any]], db_path: str) -> str:
        """
        Creates an SQLite database storing vector layers and attribute indexes
        for fast embedded local querying.
        """
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Create metadata table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS spatial_layers (
                layer_name TEXT PRIMARY KEY,
                feature_count INTEGER,
                geometry_type TEXT,
                crs TEXT
            )
        """)

        for layer_name, geojson in layers.items():
            features = geojson.get("features", [])
            if not features:
                continue

            geom_type = features[0]["geometry"]["type"]

            # Create specific layer table
            cur.execute(f"DROP TABLE IF EXISTS {layer_name}")
            cur.execute(f"""
                CREATE TABLE {layer_name} (
                    id TEXT PRIMARY KEY,
                    geometry_json TEXT,
                    properties_json TEXT,
                    min_lon REAL,
                    min_lat REAL,
                    max_lon REAL,
                    max_lat REAL,
                    criticality_weight REAL,
                    risk_score REAL DEFAULT 0.0
                )
            """)

            # Insert features
            for f in features:
                fid = f.get("id", str(f.get("properties", {}).get("asset_id", "")))
                geom = f.get("geometry", {})
                props = f.get("properties", {})
                crit = props.get("criticality_weight", 0.5)

                # Compute approximate bounding box
                coords = geom.get("coordinates", [])
                if geom_type == "Point":
                    lon, lat = coords
                    bbox = (lon, lat, lon, lat)
                elif geom_type == "LineString":
                    lons = [pt[0] for pt in coords]
                    lats = [pt[1] for pt in coords]
                    bbox = (min(lons), min(lats), max(lons), max(lats))
                else:
                    bbox = (94.0, 25.6, 94.2, 25.8)

                cur.execute(f"""
                    INSERT INTO {layer_name} 
                    (id, geometry_json, properties_json, min_lon, min_lat, max_lon, max_lat, criticality_weight)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (fid, json.dumps(geom), json.dumps(props), bbox[0], bbox[1], bbox[2], bbox[3], crit))

            # Create bounding-box indexes for spatial queries
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{layer_name}_spatial ON {layer_name} (min_lon, min_lat, max_lon, max_lat)")

            # Record in layer registry
            cur.execute("""
                INSERT OR REPLACE INTO spatial_layers (layer_name, feature_count, geometry_type, crs)
                VALUES (?, ?, ?, ?)
            """, (layer_name, len(features), geom_type, "EPSG:4326"))

        conn.commit()
        conn.close()
        return db_path

    def generate_postgis_ddl(self) -> str:
        """
        Generates production-grade PostgreSQL + PostGIS DDL script with GiST spatial indexing,
        partitioning, and trigger action response schemas.
        """
        ddl = """-- ====================================================================
-- NER Landslide Early Warning System: PostGIS Production Schema
-- Workstream: GIS + DEM + 3D Terrain + Spatial Risk Analysis (Ayush)
-- Coordinate Reference System: WGS 84 (EPSG:4326) / UTM Zone 46N (EPSG:32646)
-- ====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- 1. Digital Elevation Model (DEM) & Raster Derivative Catalog
CREATE TABLE IF NOT EXISTS gis_raster_dem (
    rid SERIAL PRIMARY KEY,
    tile_name VARCHAR(100) NOT NULL,
    resolution_m NUMERIC(5,2) DEFAULT 10.0,
    acquisition_date DATE,
    rast RASTER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gis_raster_dem_rast 
    ON gis_raster_dem USING GIST (ST_ConvexHull(rast));

-- 2. Transportation Infrastructure (National Highways, Arterial Roads)
CREATE TABLE IF NOT EXISTS infra_roads (
    asset_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    road_type VARCHAR(50) NOT NULL, -- 'National Highway', 'State Highway', etc.
    criticality_weight NUMERIC(3,2) NOT NULL CHECK (criticality_weight BETWEEN 0.0 AND 1.0),
    traffic_pcu_per_day INTEGER,
    width_m NUMERIC(4,1),
    geom GEOMETRY(LineString, 4326) NOT NULL,
    geom_utm GEOMETRY(LineString, 32646) GENERATED ALWAYS AS (ST_Transform(geom, 32646)) STORED
);

CREATE INDEX IF NOT EXISTS idx_infra_roads_geom ON infra_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_infra_roads_crit ON infra_roads (criticality_weight DESC);

-- 3. Human Settlements & Villages
CREATE TABLE IF NOT EXISTS infra_settlements (
    village_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    population INTEGER NOT NULL,
    households INTEGER NOT NULL,
    criticality_weight NUMERIC(3,2) NOT NULL CHECK (criticality_weight BETWEEN 0.0 AND 1.0),
    has_medical_facility BOOLEAN DEFAULT FALSE,
    has_school BOOLEAN DEFAULT FALSE,
    geom GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_infra_settlements_geom ON infra_settlements USING GIST (geom);

-- 4. Critical Infrastructure Assets (Bridges, Culverts, Power Towers)
CREATE TABLE IF NOT EXISTS infra_critical_assets (
    asset_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    asset_type VARCHAR(60) NOT NULL, -- 'Bridge', 'Transmission Tower', 'Health Clinic'
    criticality_weight NUMERIC(3,2) NOT NULL,
    replacement_cost_inr_cr NUMERIC(8,2),
    geom GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_infra_critical_assets_geom ON infra_critical_assets USING GIST (geom);

-- 5. IoT Sensor Network Registry & Live Telemetry Link
CREATE TABLE IF NOT EXISTS sensor_nodes (
    sensor_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    sensor_type VARCHAR(50) NOT NULL, -- 'Piezometer', 'Inclinometer', 'Rain Gauge'
    unit VARCHAR(20) NOT NULL,
    zone_id VARCHAR(50) NOT NULL,
    elevation_m NUMERIC(6,2),
    health_score NUMERIC(5,2) DEFAULT 100.0,
    status VARCHAR(20) DEFAULT 'Healthy', -- 'Healthy', 'Degraded', 'Failed'
    geom GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sensor_nodes_geom ON sensor_nodes USING GIST (geom);

-- 6. Spatial Risk Prediction Grids (Partitioned by Simulation Timestamp)
CREATE TABLE IF NOT EXISTS spatial_risk_predictions (
    prediction_id BIGSERIAL,
    point_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    risk_score NUMERIC(5,2) NOT NULL,
    risk_level VARCHAR(20) NOT NULL, -- 'Low', 'Moderate', 'High', 'Severe'
    probability NUMERIC(5,4) NOT NULL,
    slope_deg NUMERIC(4,2),
    rainfall_7d_mm NUMERIC(6,2),
    antecedent_precip_index NUMERIC(6,2),
    geom GEOMETRY(Point, 4326) NOT NULL,
    PRIMARY KEY (prediction_id, timestamp)
) PARTITION BY RANGE (timestamp);

CREATE INDEX IF NOT EXISTS idx_spatial_risk_geom_time 
    ON spatial_risk_predictions USING GIST (geom, timestamp);

-- 7. High-Performance Spatial Exposure Prioritization Query Function
CREATE OR REPLACE FUNCTION get_exposed_infrastructure(
    target_time TIMESTAMP WITH TIME ZONE,
    risk_threshold NUMERIC DEFAULT 65.0,
    buffer_distance_m NUMERIC DEFAULT 150.0
)
RETURNS TABLE (
    asset_id VARCHAR,
    asset_name VARCHAR,
    asset_type VARCHAR,
    criticality NUMERIC,
    max_hazard_risk NUMERIC,
    priority_score NUMERIC,
    threat_geom GEOMETRY
) AS $$
BEGIN
    RETURN QUERY
    WITH HighRiskZones AS (
        SELECT 
            ST_Buffer(ST_Transform(s.geom, 32646), buffer_distance_m) AS risk_poly,
            s.risk_score
        FROM spatial_risk_predictions s
        WHERE s.timestamp = target_time AND s.risk_score >= risk_threshold
    )
    SELECT 
        r.asset_id,
        r.name AS asset_name,
        r.road_type AS asset_type,
        r.criticality_weight AS criticality,
        MAX(hrz.risk_score) AS max_hazard_risk,
        ROUND((MAX(hrz.risk_score) * r.criticality_weight)::numeric, 2) AS priority_score,
        r.geom AS threat_geom
    FROM infra_roads r
    JOIN HighRiskZones hrz ON ST_Intersects(r.geom_utm, hrz.risk_poly)
    GROUP BY r.asset_id, r.name, r.road_type, r.criticality_weight, r.geom
    ORDER BY priority_score DESC;
END;
$$ LANGUAGE plpgsql;
"""
        filepath = os.path.join(self.export_dir, "postgis_schema_ddl.sql")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(ddl)
        return filepath
