"""
NER Landslide Early Warning System — GIS Module Pipeline Orchestrator
=====================================================================
Executes the complete GIS workstream:
DEM Generation -> Terrain Derivatives -> Spatial Infrastructure ->
Multi-temporal ML Risk Simulation -> Exposure Prioritization (R x I) ->
Vector/Raster DB Export -> WebGL Dashboard Payload Generation.
"""

from __future__ import annotations
import os
import sys
import json
from dataclasses import asdict
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.gis.dem_engine import DEMEngine
from src.gis.terrain_derivatives import TerrainDerivativeCalculator
from src.gis.infrastructure_engine import InfrastructureEngine
from src.gis.spatial_storage import SpatialStorageEngine
from src.gis.risk_exposure_engine import RiskExposureEngine


def run_full_pipeline(output_base: str = "data"):
    print("================================================================================")
    print("      NER LANDSLIDE EARLY WARNING SYSTEM -- GIS & 3D SPATIAL RISK ENGINE        ")
    print("================================================================================")
    
    os.makedirs(f"{output_base}/dem", exist_ok=True)
    os.makedirs(f"{output_base}/vector", exist_ok=True)
    os.makedirs(f"{output_base}/risk", exist_ok=True)
    os.makedirs(f"{output_base}/export", exist_ok=True)

    # 1. DEM Acquisition and Geomorphological Modeling
    print("\n[Step 1/6] Sourcing and synthesizing High-Resolution DEM (Kohima-NH29 Corridor)...")
    dem_engine = DEMEngine(cell_size_m=10.0)
    dem = dem_engine.generate_synthetic_kohima_dem(
        bounds=(94.02, 25.62, 94.14, 25.72),
        grid_size=(100, 100),
        random_seed=42
    )
    
    dem_engine.export_esri_ascii(dem, f"{output_base}/dem/kohima_corridor_dem.asc")
    with open(f"{output_base}/dem/dem_metadata.json", "w") as f:
        json.dump(dem.to_dict(), f, indent=2)
    print(f"  [OK] DEM synthesized: {dem.rows}x{dem.cols} grid (10m resolution, {dem.rows*dem.cols} cells)")
    print(f"  [OK] Elevation span: {np.min(dem.elevation):.1f}m to {np.max(dem.elevation):.1f}m AMSL")
    print(f"  [OK] Exported: {output_base}/dem/kohima_corridor_dem.asc (ESRI ASCII Grid)")

    # 2. Multi-Band Terrain Derivatives Engine
    print("\n[Step 2/6] Calculating 7 Geomorphological and Hydrological Terrain Derivatives...")
    calculator = TerrainDerivativeCalculator(cell_size_m=10.0)
    derivatives = calculator.calculate_all(dem.elevation, bounds=(dem.min_lon, dem.min_lat, dem.max_lon, dem.max_lat))
    
    extra_layers = {
        "slope_deg": derivatives.slope_deg,
        "aspect_deg": derivatives.aspect_deg,
        "profile_curvature": derivatives.profile_curvature,
        "planform_curvature": derivatives.planform_curvature,
        "tri": derivatives.tri,
        "twi": derivatives.twi,
        "flow_accumulation": derivatives.flow_accumulation,
        "stream_network": derivatives.stream_network
    }
    dem_engine.export_npz(dem, f"{output_base}/dem/kohima_terrain_derivatives.npz", extra_layers=extra_layers)
    print(f"  [OK] Slope: min {np.min(derivatives.slope_deg):.1f} deg, mean {np.mean(derivatives.slope_deg):.1f} deg, max {np.max(derivatives.slope_deg):.1f} deg")
    print(f"  [OK] TRI (Ruggedness): mean {np.mean(derivatives.tri):.1f}m | TWI (Wetness): max {np.max(derivatives.twi):.1f}")
    print(f"  [OK] D8 Drainage network extracted: {np.sum(derivatives.stream_network)} stream channel cells")
    print(f"  [OK] Exported: {output_base}/dem/kohima_terrain_derivatives.npz")

    # 3. Vector Infrastructure and Sensor Array Generation
    print("\n[Step 3/6] Building Vector Infrastructure and IoT Sensor Network Layers...")
    infra_engine = InfrastructureEngine(bounds=(dem.min_lon, dem.min_lat, dem.max_lon, dem.max_lat))
    infra = infra_engine.generate_all(random_seed=42)
    
    storage = SpatialStorageEngine(export_dir=f"{output_base}/export")
    storage.save_geojson(infra.roads, "../vector/roads.geojson")
    storage.save_geojson(infra.settlements, "../vector/settlements.geojson")
    storage.save_geojson(infra.rivers, "../vector/rivers.geojson")
    storage.save_geojson(infra.critical_assets, "../vector/critical_assets.geojson")
    storage.save_geojson(infra.sensors, "../vector/sensor_network.geojson")
    
    print(f"  [OK] Roads: {len(infra.roads['features'])} segments (NH-29 Lifeline + Arterials)")
    print(f"  [OK] Settlements: {len(infra.settlements['features'])} village clusters (Population: {sum(f['properties']['population'] for f in infra.settlements['features'])})")
    print(f"  [OK] Critical Assets: {len(infra.critical_assets['features'])} assets (Bridges, 132kV Power Towers, CHC)")
    print(f"  [OK] IoT Sensor Nodes: {len(infra.sensors['features'])} stations (Piezometers, Inclinometers, AWS)")

    # 4. Multi-Temporal ML Risk Simulation
    print("\n[Step 4/6] Executing Multi-Temporal Slope Stability Risk Simulation (6 Timesteps)...")
    risk_engine = RiskExposureEngine(dem=dem, derivatives=derivatives)
    time_series_grids = risk_engine.simulate_advancing_monsoon_scenario()
    
    ts_dict = {}
    reports_all = []
    for g in time_series_grids:
        ts_dict[f"risk_{g.time_label}"] = g.risk_grid
        rep = risk_engine.evaluate_exposure_and_prioritization(g, infra)
        reports_all.append(asdict(rep))
        print(f"  * {g.time_label:<28} | Max Risk: {g.max_risk_score:5.1f}% | High-Risk Area: {g.high_risk_area_km2:5.2f} sq km | Threatened Pop: {rep.threatened_population:<5} | Alert: {rep.evacuation_alert_level}")

    np.savez_compressed(f"{output_base}/risk/spatial_risk_timesteps.npz", **ts_dict)
    with open(f"{output_base}/risk/exposure_summary_all_timesteps.json", "w") as f:
        json.dump(reports_all, f, indent=2)

    # 5. Spatial Storage, PostGIS DDL and SQLite GeoPackage
    print("\n[Step 5/6] Serializing Spatial Storage, PostGIS Schema DDL, and SQLite Database...")
    sql_path = storage.generate_postgis_ddl()
    sqlite_layers = {
        "infra_roads": infra.roads,
        "infra_settlements": infra.settlements,
        "infra_rivers": infra.rivers,
        "infra_critical_assets": infra.critical_assets,
        "sensor_nodes": infra.sensors
    }
    sqlite_path = storage.export_sqlite_geopackage_mock(sqlite_layers, f"{output_base}/export/corridor_spatial.sqlite")
    print(f"  [OK] PostGIS DDL generated: {sql_path}")
    print(f"  [OK] SQLite Spatial DB built: {sqlite_path} with spatial indexes")

    # 6. WebGL 2D/3D Dashboard Payload Assembly
    print("\n[Step 6/6] Generating Integrated WebGL 2D/3D Digital Twin Payload...")
    # Prepare compressed grid arrays for frontend rendering
    elevation_list = dem.elevation.tolist()
    slope_list = derivatives.slope_deg.tolist()
    aspect_list = derivatives.aspect_deg.tolist()
    tri_list = derivatives.tri.tolist()
    twi_list = derivatives.twi.tolist()
    
    risk_timesteps_payload = []
    for g in time_series_grids:
        risk_timesteps_payload.append({
            "label": g.time_label,
            "rainfall_24h_mm": g.rainfall_24h_mm,
            "rainfall_72h_mm": g.rainfall_72h_mm,
            "rainfall_7d_mm": g.rainfall_7d_mm,
            "mean_risk": round(g.mean_risk_score, 1),
            "max_risk": round(g.max_risk_score, 1),
            "high_risk_area_km2": g.high_risk_area_km2,
            "grid": g.risk_grid.tolist()
        })

    dashboard_data = {
        "metadata": {
            "project": "NER Landslide Early Warning Platform",
            "module": "GIS + DEM + 3D Terrain + Spatial Risk Analysis (Ayush)",
            "study_area": "Kohima-Dimapur (NH-29) Corridor, Nagaland",
            "crs": "EPSG:4326 (WGS84)",
            "bounds": [dem.min_lon, dem.min_lat, dem.max_lon, dem.max_lat],
            "rows": dem.rows,
            "cols": dem.cols,
            "cell_size_m": dem.cell_size_m,
            "elevation_min": float(np.min(dem.elevation)),
            "elevation_max": float(np.max(dem.elevation))
        },
        "rasters": {
            "elevation": elevation_list,
            "slope": slope_list,
            "aspect": aspect_list,
            "tri": tri_list,
            "twi": twi_list
        },
        "vectors": {
            "roads": infra.roads,
            "settlements": infra.settlements,
            "rivers": infra.rivers,
            "critical_assets": infra.critical_assets,
            "sensors": infra.sensors
        },
        "risk_simulation": {
            "timesteps": risk_timesteps_payload,
            "exposure_reports": reports_all
        }
    }

    payload_path = f"{output_base}/export/dashboard_payload.json"
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f)
    print(f"  [OK] WebGL payload exported: {payload_path} ({os.path.getsize(payload_path) / 1024:.1f} KB)")
    
    print("\n================================================================================")
    print("                     GIS PIPELINE EXECUTION COMPLETE!                           ")
    print("================================================================================")
    return dashboard_data


if __name__ == "__main__":
    run_full_pipeline()
