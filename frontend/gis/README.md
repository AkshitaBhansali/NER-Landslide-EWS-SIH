# NER Landslide Early Warning Platform — GIS & 3D Spatial Risk Module

**Author:** Ayush Kumar Maurya ([@DrustO9](https://github.com/DrustO9))  
**Workstream:** GIS + DEM + 3D Terrain + Spatial Risk Analysis  
**Corridor Focus:** Kohima–Dimapur (NH-29 / Dzüdza River Gorge), Nagaland  
**Status:** Version 1 (V1) Prototype Complete  

---

## 1. Overview

This repository hosts the **GIS, DEM, 3D digital-twin terrain, and spatial risk exposure engine** for the North Eastern Region (NER) Landslide Early Warning Platform.

The system addresses the primary operational question for disaster response and highway management:
> **“Where is the landslide risk occurring, how does it evolve over time, and what roads, settlements, rivers, and critical infrastructure are exposed?”**

The pipeline integrates:
$$\text{DEM / Terrain} \longrightarrow \text{7 Terrain Derivatives} \longrightarrow \text{Spatial Storage (PostGIS / SQLite)} \longrightarrow \text{Multi-Temporal ML Risk Simulation} \longrightarrow \text{Exposure Prioritization } (R \times I) \longrightarrow \text{2D Multi-Layer Map} \longrightarrow \text{3D Digital Twin}$$

---

## 2. Key Capabilities & Pipeline

### 1. High-Resolution DEM & Terrain Derivatives
- Synthesizes and models high-resolution ($10\text{m}$ grid) geomorphological mountain topography matching the Kohima–Dimapur mountain corridor ($720\text{m} - 2,312\text{m}$ AMSL).
- Computes **7 core topographic and hydrological derivatives** in **23.17 ms** (< 2MB RAM) using vectorized NumPy/SciPy:
  - **Slope ($\beta$):** Horn's weighted 8-neighbor finite-difference method ($0^\circ - 85^\circ$, Mean: $61.7^\circ$).
  - **Aspect ($\alpha$):** Compass azimuth ($0^\circ - 360^\circ$ clockwise from North).
  - **Planform Curvature ($K_{plan}$):** Flow divergence on ridges / convergence in hollows.
  - **Profile Curvature ($K_{prof}$):** Flow acceleration / deceleration along gradient.
  - **Terrain Ruggedness Index (TRI):** Riley et al. heterogeneity measure.
  - **Topographic Wetness Index (TWI):** $\ln(A_s / \tan\beta)$ steady-state moisture and hollow convergence.
  - **D8 Hydrological Routing:** Upstream catchment accumulation and drainage stream network extraction ($531\text{ channel cells}$).

### 2. Multi-Layer Infrastructure & IoT Sensor Array
- **Transportation Lifelines:** NH-29 Highway segmented into 15 monitored chainage sectors (Km 142 to 158), plus arterial hill bypasses.
- **Human Settlements:** 5 rural village clusters (11,360 total population) with vulnerability ratings.
- **Hydrological Network:** Dzüdza perennial canyon river and flash-flood tributaries with active toe-scour ratings.
- **Critical Infrastructure:** Dzüdza major bridge, culverts, 132kV high-tension power transmission towers, and Community Health Center.
- **IoT Early Warning Sensors:** 10 telemetry stations (pore-pressure piezometers, borehole inclinometers, surface tiltmeters, rain gauges) matching `SENSOR_READING_SCHEMA`.

### 3. Multi-Temporal ML Risk & Prioritization Engine
- Simulates 6 operational timesteps ($T+0\text{h} \to T+72\text{h}$) tracking an advancing monsoon depression (rainfall climbing from 10mm to 185mm/24h, saturation ratio reaching 85%).
- Computes the **Infrastructure Priority Score**:
  $$\text{Priority Score} = \text{Hazard Risk Score} \times \text{Asset Criticality Weight} \times \text{Vulnerability Factor}$$
- Ranks evacuation priorities, identifies impending road closures, and exports structured JSON evacuation action directives.

### 4. Interactive 2D & 3D WebGL Digital Twin Dashboard
- **3D Digital Twin View (Three.js WebGL):**
  - Real elevation extruded 3D mesh with directional sun lighting and shadows.
  - Dynamically draped risk heatmaps updating in real-time with the timeline slider.
  - 3D pulsing IoT sensor markers, extruded road ribbons, bridge models, and village cones.
  - 3D Raycasting: clicking on any 3D asset opens the inspection modal with live metrics.
  - 4 Camera Presets: Perspective, Dzüdza Gorge Flank, Top-Down Bird's Eye, and NH-29 Highway alignment.
- **2D Multi-Layer Map (Leaflet):**
  - Georeferenced raster heatmap canvas overlay + vector GeoJSON overlays.
  - Layer toggles for Elevation, Slope, TWI, TRI, Roads, Settlements, Rivers, and Sensors.
- **Monsoon Scenario Player:**
  - Play / Pause / Scrub controls across the 72-hour sequence with live updating risk gauges, threatened population counters, and priority action lists.
  - One-click **Export JSON** for emergency dispatch orders.

---

## 3. Recommended Production Stack

| Component | Selected Technology | Role |
|---|---|---|
| **Raster Processing** | **GRASS / GDAL** | Headless automated DEM derivative calculation and tiling |
| **Desktop GIS** | **QGIS** | Offline specialist auditing, cartographic styling, and field survey QA |
| **Spatial Database** | **PostGIS (PostgreSQL)** | R-Tree GiST indexing, spatial overlay joins, and pgRouting detour planning |
| **Vector Baseline** | **OpenStreetMap (OSM)** | Open regional roads, waterways, and settlement data |
| **2D Web Mapping** | **MapLibre GL JS** | GPU-accelerated client vector tile rendering and alert overlays |
| **3D Digital Twin** | **CesiumJS** | OGC 3D Tiles and true georeferenced ellipsoidal terrain streaming |

---

## 4. Repository Structure

```
NER_Landslide_GIS/
├── context.md                    # Project specifications, interfaces, and architecture
├── memory.md                     # Engineering audit log & benchmarks
├── README.md                     # Project overview and reproduction guide
├── .gitignore                    # Git exclusions
├── docs/
│   └── GIS_EVALUATION_REPORT.md  # Detailed benchmark report across GIS toolchains
├── src/
│   ├── gis/
│   │   ├── __init__.py
│   │   ├── dem_engine.py         # DEM generation, georeferencing, ASCII grid & NPZ export
│   │   ├── terrain_derivatives.py# 7 geomorphological & hydrological derivatives
│   │   ├── infrastructure_engine.py # Road lifelines, settlements, rivers, assets, sensors
│   │   ├── spatial_storage.py    # GeoJSON, SQLite spatial DB, and PostGIS DDL generator
│   │   └── risk_exposure_engine.py # Infinite-slope risk model & R x I prioritization
│   ├── run_gis_pipeline.py       # End-to-end pipeline execution script
│   └── build_dashboard.py        # Web visualizer compiler
├── data/
│   ├── dem/                      # kohima_corridor_dem.asc (ESRI ASCII Grid), NPZ derivatives
│   ├── vector/                   # GeoJSON vector layers (roads, villages, rivers, assets, sensors)
│   ├── risk/                     # Multi-timestep risk arrays & exposure summaries
│   └── export/                   # postgis_schema_ddl.sql, corridor_spatial.sqlite, dashboard_payload.json
└── dist/
    └── index.html                # Standalone interactive 2D/3D WebGL Digital Twin Dashboard
```

---

## 5. How to Run Locally

### 1. Requirements
Python 3.10+ with standard scientific packages:
```bash
python -c "import numpy, scipy, pandas; print('Environment OK')"
```

### 2. Run the GIS Pipeline
```bash
python src/run_gis_pipeline.py
```
This synthesizes the DEM, computes all 7 derivatives, generates vector layers, runs the 6-timestep monsoon simulation, exports SQLite/PostGIS schemas, and builds the WebGL payload.

### 3. Open the Interactive Digital Twin
Open `dist/index.html` in any modern web browser.
- Toggle between **3D Terrain Digital Twin** and **2D GIS Multi-Layer Map**.
- Scrub the **Monsoon Progression Slider** ($T+0\text{h} \to T+72\text{h}$) to see live dynamic risk heatmaps and priority action rankings.
- Click on any road segment, bridge, village, or sensor pin to inspect real-time attributes.
- Click **Export JSON** in the right panel to download structured evacuation and resource dispatch orders.

---

## 6. License
Open source under the [MIT License](LICENSE).
