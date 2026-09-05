# Engineering Memory & Audit Log — NER Landslide Early Warning GIS Module

## 2026-08-31T21:20:00+05:30 — CHANGE-001

### Change
Workspace initialization, role configuration, and reference material ingestion for Ayush's GIS + DEM + 3D Terrain + Spatial Risk workstream.

### Files
- Inspected `Fallen_Rock.pdf` (Previous-year SIH winning project presentation)
- Inspected `Mine2Energy-AI-standalone.html`
- Cloned reference repositories into `references/`:
  - `references/NER_Landslide_EWS` (Current work by Eisa/Saksham/Krish/Akshita)
  - `references/Fallen_Rock_SIH` (2025 Rockfall prediction platform)
- Created `context.md` (Stable project context & technical specifications)
- Created `memory.md` (Chronological engineering audit log)

### Database
- Evaluated schema requirements for PostGIS / GeoPackage / GeoJSON:
  - Raster metadata schema for DEM and derivative bands (elevation, slope, aspect, curvature, TRI, TWI, flow).
  - Vector infrastructure schema: transportation (roads, highways), settlements (villages, towns), water (streams, rivers), critical assets (bridges, power lines, hospitals).
  - Sensor telemetry schema with geolocated coordinates (`latitude`, `longitude`, `elevation_m`).
  - Spatial risk output schema with time-varying hazard probability and criticality-weighted exposure.

### Experiments
- Analyzed `NER_Landslide_EWS` physics simulation (`simulation/physics_slope_model.py`) and ML training pipelines (`ml/train_risk_model.py`).
- Mapped observable features (`slope_deg`, `rainfall_24h_mm`, `rainfall_72h_mm`, `rainfall_7d_mm`, `antecedent_precip_index`) to GIS terrain layers.
- Formulated comparative trade-off matrix across GIS frameworks: ArcGIS vs QGIS vs MapLibre/Leaflet vs Three.js vs Cesium vs PostGIS vs DuckDB-Spatial.

### Decisions
1. **Open-Source-First Architecture:** Selected open-source geospatial stack (`GDAL/Rasterio/Shapely` in Python backend, `PostGIS`/`GeoPackage` for spatial storage, `Three.js` + `Leaflet/MapLibre` for 2D/3D visualization).
2. **Infinite-Slope Physical Grounding:** Replaced discrete boulder trajectory physics (from 2025 Fallen_Rock) with continuous rainfall-induced pore-water pressure and factor-of-safety slip surface models suitable for regional NER colluvial soils.
3. **Decoupled Geospatial Interface Contract:** Defined clear JSON interface contracts with upstream ML classifiers and downstream alert dispatching services.
4. **Study Area Selection:** Designated the high-risk Kohima–Dimapur corridor (Nagaland / NH-29) in the North Eastern Region as the primary focus area for the V1 prototype.

### Next Action
- Implement geomorphologically realistic synthetic DEM and multi-band terrain derivatives engine (`elevation`, `slope`, `aspect`, `curvature`, `TRI`, `TWI`, `drainage`).
- Build vector infrastructure and sensor layer generator.
- Implement spatial risk mapping and infrastructure exposure prioritization engine ($R \times I$).

---

## 2026-08-31T22:04:00+05:30 — CHANGE-002

### Change
Implemented complete end-to-end Version 1 (V1) GIS, DEM, multi-temporal risk simulation, exposure prioritization, comparative benchmarking, and 2D/3D WebGL digital twin platform.

### Files
- Created `src/gis/dem_engine.py` (High-resolution DEM generation, georeferencing, ASCII grid & NPZ export)
- Created `src/gis/terrain_derivatives.py` (Horn's slope/aspect, Zevenbergen curvature, TRI, TWI, D8 flow accumulation)
- Created `src/gis/infrastructure_engine.py` (NH-29 sectors, villages, rivers, critical lifelines, and IoT sensor arrays)
- Created `src/gis/spatial_storage.py` (GeoJSON serializer, SQLite/GeoPackage generator, production PostGIS DDL script)
- Created `src/gis/risk_exposure_engine.py` (Infinite-slope Factor-of-Safety risk engine, multi-timestep simulation, $R \times I$ prioritization)
- Created `src/run_gis_pipeline.py` (End-to-end pipeline orchestrator)
- Created `src/build_dashboard.py` (Standalone 2D/3D WebGL dashboard compiler)
- Created `docs/GIS_EVALUATION_REPORT.md` (Comparative benchmark report across ArcGIS, QGIS, Three.js, MapLibre, PostGIS, GEE)
- Generated data artifacts:
  - `data/dem/kohima_corridor_dem.asc` (ESRI ASCII Grid)
  - `data/dem/kohima_terrain_derivatives.npz` (7-band derivative raster)
  - `data/vector/*.geojson` (5 infrastructure GeoJSON layers)
  - `data/risk/spatial_risk_timesteps.npz` (6-timestep monsoon risk simulation)
  - `data/export/postgis_schema_ddl.sql` (Production PostGIS DDL with GiST indexes)
  - `data/export/corridor_spatial.sqlite` (Spatial database with bounding-box index)
  - `data/export/dashboard_payload.json` (798.4 KB WebGL digital twin data bundle)
- Created `dist/index.html` (Standalone, interactive 2D/3D Digital Twin Early Warning Dashboard)

### Database / Schema Changes
- Created SQLite spatial tables (`infra_roads`, `infra_settlements`, `infra_rivers`, `infra_critical_assets`, `sensor_nodes`) with bounding box spatial indexing.
- Authored production PostGIS DDL schema with `GEOMETRY(LineString, 4326)`, `GEOMETRY(Point, 4326)`, `ST_Transform` to UTM Zone 46N (EPSG:32646), and `get_exposed_infrastructure` PL/pgSQL spatial query function.

### Experiments & Benchmarks
- Benchmark results on standard CPU (10,000 cells / 10m DEM):
  - Horn's slope: 1.84 ms
  - Compass aspect: 2.12 ms
  - Planform/Profile curvature: 6.96 ms
  - Riley TRI: 2.90 ms
  - D8 flow routing: 8.20 ms
  - TWI: 1.15 ms
  - Total 7-band stack: **23.17 ms** (< 2 MB memory footprint).
- Tested 6 operational timesteps ($T+0\text{h} \to T+72\text{h}$) simulating an advancing monsoon depression (rainfall rising from 10mm to 185mm/24h, saturation ratio climbing to 85%).
- Automated headless browser validation completed with 0 console errors, validating Three.js 3D mesh rendering, Leaflet 2D maps, and interactive time-series scrubbing.

### Decisions
1. **Zero-Dependency Core Python Backend:** Implemented pure NumPy/SciPy vectorized algorithms for all terrain derivatives, removing external binary/GDAL installation friction while achieving sub-25ms regional processing.
2. **Prioritization Formula ($R \times I$):** Formally adopted $\text{Priority Score} = \text{Hazard Risk Score} \times \text{Asset Criticality Weight} \times \text{Vulnerability Factor}$ for operational disaster resource dispatching.
3. **Dual 2D/3D Architecture:** Adopted Leaflet for fast 2D GIS multi-layer overlay navigation and Three.js WebGL for immersive 3D slope digital-twin visualization.
4. **Self-Contained Offline Bundle:** Packaged the V1 showcase in `dist/index.html` with embedded data so field officers and hackathon evaluators can run the full digital twin without cloud dependencies.

### Current V1 Status
- Complete V1 prototype fully functional, benchmarked, and verified in browser.

---

## 2026-08-31T22:58:00+05:30 — CHANGE-003

### Change
Refactored and hardened frontend button event listeners, SVG icon switching, 3D raycasting, and 2D canvas raster overlays.

### Files
- Modified `src/build_dashboard.py` (Replaced Lucide icon mutation with resilient inline SVG toggles, added card-level event delegation, Three.js raycaster, and 2D Leaflet canvas image overlays)
- Rebuilt `dist/index.html`

### Experiments & Browser Subagent Testing
- Automated browser testing verified:
  1. `2D GIS Multi-Layer Map` button switches to Leaflet 2D map with real-time draped raster heatmaps.
  2. `3D Terrain Digital Twin` button switches back to WebGL Three.js terrain mesh.
  3. `Play / Pause` button starts and pauses timeline progression ($T+0\text{h} \to T+72\text{h}$) with live statistics, gauges, and hazard charts updating every 2.2s.
  4. Layer toggle cards in left sidebar (Slope Angle, Topographic Wetness, Ruggedness, NH-29, Settlements, Rivers, Sensors) dynamically toggle geometries and active card styling.
  5. 3D and 2D asset inspection modal opens with full telemetry on click and closes cleanly with the close button.
  6. `Export JSON` triggers dynamic download of structured priority dispatch orders.
  7. Camera Presets (Perspective, Dzüdza Gorge Flank, Top-Down, NH-29 Highway) reorient camera.
- Console error count: **0 errors**.

---

## 2026-09-01T21:18:00+05:30 — CHANGE-004

### Change
Git repository initialization and published to GitHub.

### Files
- Created `.gitignore`
- Created `README.md`
- Committed 27 files tracking `src/`, `data/`, `dist/`, `docs/`, `context.md`, `memory.md`, and `README.md`
- Created public remote repository and pushed to `main` branch: `https://github.com/DrustO9/NER_Landslide_GIS`

### Decisions
- Published under user GitHub account `@DrustO9` as a dedicated open-source repository `NER_Landslide_GIS`.
