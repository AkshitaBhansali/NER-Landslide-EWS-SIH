# NER Landslide Early Warning System — GIS & 3D Spatial Risk Module

## 1. Project Goal

Develop a production-grade, open-source-first GIS and 3D spatial risk intelligence engine for the **North Eastern Region (NER) Landslide Early Warning Platform**. 

The module answers the primary operational question for disaster response and civil administration:
> **“Where is the landslide risk occurring, how does it evolve over time, and what roads, settlements, rivers, and critical infrastructure are exposed?”**

The end goal for **Version 1 (V1)** is a complete, runnable GIS pipeline:
$$\text{DEM / Terrain} \longrightarrow \text{Terrain Derivatives} \longrightarrow \text{Spatial Storage} \longrightarrow \text{Synthetic/Live ML Risk Output} \longrightarrow \text{Spatial Risk Layers \& Heatmaps} \longrightarrow \text{Exposure \& Prioritization Engine} \longrightarrow \text{2D Interactive Map} \longrightarrow \text{3D Digital Twin Terrain}$$

---

## 2. Workstream Scope & Ownership (Ayush)

### In-Scope (Ayush's Responsibilities)
- **DEM Acquisition & Processing:** Sourcing, clipping, resampling, and deriving core topographic derivatives (elevation, slope, aspect, profile/planform curvature, flow accumulation/drainage networks, Terrain Ruggedness Index [TRI], and Topographic Wetness Index [TWI]).
- **Spatial Data Architecture:** Open-source spatial storage and querying (GeoTIFF, GeoJSON, Shapefiles, GeoPackage, PostGIS / DuckDB-Spatial) for regional grids and infrastructure vectors.
- **Risk Ingestion & Spatial Mapping:** Ingesting ML risk prediction tuples (`risk_score`, `risk_level`, `probability`, `contributing_factors`) and projecting them across continuous 2D spatial grids and 3D terrain meshes.
- **Exposure & Prioritization Engine:** Spatial intersections with transportation corridors (highways, arterial roads), human settlements (villages, towns), watercourses (rivers, flash-flood zones), and critical infrastructure (bridges, transmission towers, hospitals). Computing Infrastructure Prioritization:
  $$\text{Priority Score} = \text{Hazard Risk Score} \times \text{Asset Criticality Index}$$
- **2D/3D Visualization:** Multi-layered 2D map (Leaflet / MapLibre GL) and high-fidelity 3D digital-twin terrain visualization (Three.js / Cesium / Deck.gl) displaying live/synthetic sensors, terrain risk heatmaps, infrastructure, and dynamic time-series slider.
- **Benchmarking & Trade-off Matrix:** Comprehensive evaluation of GIS toolchains (ArcGIS, QGIS, Mapbox, MapLibre, Cesium, GEE, PostGIS, DuckDB Spatial, Three.js).

### Out-of-Scope (Interface Boundaries)
- **Sensor Telemetry & Cleaning:** Handled by upstream IoT/pipeline team (Saksham/Eisa).
- **Core ML Model Architecture:** Handled by ML team (Eisa/Krish). Ayush consumes ML outputs and feeds DEM derivatives back to the ML pipeline.
- **Alert Dispatching (SMS/Email/CAP Protocols):** Handled by backend alerting engine (Akshita/Backend).

---

## 3. Team Interface Contracts

```
[IoT / Telemetry Feed]
        │
        ▼
[Data Pipeline & Sensor Health (Saksham / Eisa)]
        │  (Sensor streams, cleaning, health index)
        ▼
[ML Risk Classifier (Eisa / Krish)]  ◄─────── [GIS Terrain Derivatives: Slope, Aspect, TWI] (Ayush)
        │
        ▼ (risk_score, risk_level, probability, contributing_factors)
[GIS Spatial Risk & Exposure Engine (Ayush)] ───► [Exposure Metrics & Prioritization]
        │                                                    │
        ▼                                                    ▼
[2D Multi-layer Map & 3D Digital Twin (Ayush)]       [Backend Alert Dispatch (Akshita)]
```

### Upstream Contract (ML $\to$ GIS)
Ayush's pipeline ingests predictions following the canonical schema:
```json
{
  "point_id": "LOC_NER_0042",
  "latitude": 25.6741,
  "longitude": 94.1105,
  "timestamp": "2026-08-31T21:00:00Z",
  "risk_score": 78.4,
  "risk_level": "High",
  "probability": 0.7842,
  "contributing_factors": {
    "slope_deg": 0.651,
    "rainfall_7d_mm": 0.134,
    "antecedent_precip_index": 0.101,
    "rainfall_72h_mm": 0.084,
    "rainfall_24h_mm": 0.030
  }
}
```

### Downstream Contract (GIS $\to$ Backend / Alerts)
Ayush's exposure engine emits structured impact reports:
```json
{
  "zone_id": "ZONE_NH29_KOHIMA_03",
  "bounding_box": [94.08, 25.65, 94.15, 25.72],
  "max_risk_score": 88.5,
  "risk_level": "Severe",
  "exposed_infrastructure": {
    "roads": [
      { "id": "NH-29", "name": "Dimapur-Kohima Highway", "type": "National Highway", "criticality": 1.0, "exposed_length_km": 3.4, "priority_score": 88.5 }
    ],
    "villages": [
      { "id": "VIL_012", "name": "Zubza", "population": 2450, "criticality": 0.9, "priority_score": 79.65 }
    ],
    "critical_assets": [
      { "id": "BRG_004", "type": "Bridge", "name": "Dzüdza Bridge", "criticality": 1.0, "priority_score": 88.5 }
    ]
  },
  "evacuation_priority_ranking": ["Dzüdza Bridge", "NH-29 Sector 4", "Zubza Settlement"]
}
```

---

## 4. Selected Study Area & Geographic Bounds

- **Target Region:** North Eastern Region (NER) of India.
- **Representative Focus Corridor for V1 Prototype:**
  - **Location:** Kohima–Dimapur Corridor (Nagaland / NH-29) and Shillong–Cherrapunji Escarpment (Meghalaya).
  - **Bounding Box (NER Regional):** `Lat: 21.5°N - 29.5°N, Lon: 88.0°E - 97.5°E`
  - **High-Risk Prototype Bounding Box (Kohima Focus):** `Lat: 25.60°N - 25.75°N, Lon: 94.00°E - 94.18°E`
  - **Topographic Profile:** Elevations ranging from 200m to 2,400m AMSL, steep slope gradients ($25^\circ - 65^\circ$), complex folded geology, heavy monsoon precipitation ($>2,500\text{ mm/year}$).

---

## 5. Topographic Data & DEM Derivatives

### Elevation Sources
1. **ISRO/NRSC Bhuvan CartoDEM (30m / 10m):** Primary Indian national dataset.
2. **Copernicus GLO-30 / SRTM 30m:** Global open-access fallback.
3. **Synthetic High-Resolution Digital Elevation Grid:** Geomorphologically realistic synthetic DEM ($10\text{m}$ resolution) generated with realistic ridge-valley drainage patterns for testing and offline development.

### Computed Derivatives
- **Elevation ($z$):** Raw elevation raster (metres AMSL).
- **Slope ($\beta$):** First derivative of elevation (degrees $0^\circ - 90^\circ$).
- **Aspect ($\alpha$):** Downslope direction / compass heading ($0^\circ - 360^\circ$).
- **Planform Curvature ($K_p$) & Profile Curvature ($K_c$):** Flow convergence/divergence and acceleration/deceleration.
- **Terrain Ruggedness Index (TRI):** Root mean square elevation difference of neighboring cells.
- **Topographic Wetness Index ($\text{TWI} = \ln(a / \tan\beta)$):** Hydrological steady-state moisture accumulation potential.
- **Hydrological Flow & Stream Network:** D8 flow direction and accumulated upstream catchment area.

---

## 6. Technology Evaluation & Trade-off Matrix

| Tool / Technology | License / Cost | Strengths | Limitations | V1 Evaluation Decision |
|---|---|---|---|---|
| **ArcGIS Pro / Online** | Commercial / Proprietary | Turnkey enterprise GIS, polished Spatial Analyst tools | Proprietary, high licensing costs, difficult headless automated microservice integration | **Benchmark baseline only; reject for core engine** |
| **QGIS + GDAL/Rasterio** | Open Source (GPL / MIT) | Industry-standard algorithms, raster/vector pipelines, rich Python scripting | QGIS GUI is desktop-bound; core CLI/GDAL/Rasterio is ideal for backend pipelines | **Adopt GDAL/Rasterio for backend pipeline** |
| **PostGIS (PostgreSQL)** | Open Source (GPL) | Rock-solid spatial indexing (R-Tree / GiST), standard SQL spatial queries, pgRouting | Heavier memory footprint for purely synthetic lightweight V1 | **Adopt for V1/V2 database backend** |
| **DuckDB + Spatial** | Open Source (MIT) | In-process, ultra-fast columnar spatial SQL, zero external daemon required | Smaller ecosystem than PostGIS for network topology routing | **Evaluated for ultra-fast local/serverless processing** |
| **MapLibre GL JS / Leaflet** | Open Source (BSD/MIT) | Hardware-accelerated 2D vector tile rendering, smooth animations, customizable shaders | 2.5D pitch rather than full volumetric 3D mesh physics | **Adopt MapLibre/Leaflet for 2D map views** |
| **Three.js + WebGL** | Open Source (MIT) | Full 3D mesh rendering, customizable shaders, dynamic elevation extrusion, real-time lighting | Manual coordinate georeferencing needed | **Adopt for custom 3D interactive terrain twin** |
| **CesiumJS** | Open Source (Apache 2.0) | Global 3D ellipsoidal terrain, 3D Tiles standard, native georeferenced coordinates | Large runtime bundle, heavy overhead for localized site monitoring | **Evaluated for regional 3D globe view** |
| **Google Earth Engine (GEE)** | Freely accessible for research / Proprietary cloud | Massive global satellite/DEM catalogue, cloud computation | Requires active internet, API quota limits, non-trivial real-time sensor ingestion | **Adopt for satellite background ingestion** |

### Architectural Selection for V1 Prototype
- **Data & Processing:** Python (`rasterio`, `numpy`, `scipy.ndimage`, `shapely`, `geopandas`).
- **Spatial Storage:** GeoJSON, GeoTIFF, SQLite/GeoPackage + PostgreSQL/PostGIS schemas.
- **2D & 3D Visualization:** Multi-layer interactive dashboard using modern WebGL/Canvas + Three.js / Leaflet / MapLibre with full offline self-contained capability.

---

## 7. Lessons Learned from Previous Year (`Fallen_Rock`)

| Dimension | `Fallen_Rock` (2025 Open-Pit Mine) | `NER_Landslide_EWS` (2026 Regional Landslide) | Rationale for Change |
|---|---|---|---|
| **Domain & Physics** | Discrete rockfall bouncing / Rocfall3 seeder trajectories | Mass soil/colluvium slope failure along slip surface (Infinite Slope Model) | Landslides involve volumetric pore-water saturation and continuous slip planes, not single bouncing boulders. |
| **Spatial Extent** | Single open-pit mine pit ($\sim 2\text{ km} \times 2\text{ km}$) | Regional mountain corridors ($10\text{s} - 100\text{s}\text{ of km}$) | Requires multi-resolution geospatial coordinates (WGS84/UTM) and scalable tile layers. |
| **3D Rendering** | Static single GLB mine mesh with point heatmaps | Dynamic DEM terrain mesh with vector overlays (roads, rivers, villages, sensors) | Regional digital twins require dynamic layer toggles and georeferenced infrastructure layers. |
| **Exposure Analysis** | Mine benches and pit floor worker zones | Linear highway infrastructure, rural settlements, river blockages | Societal early warning requires criticality-weighted exposure scoring ($R \times I$). |

---

## 8. Current Implementation Status

- [x] Reference repository analysis (`NER_Landslide_EWS` and `Fallen_Rock_SIH`).
- [x] Context & engineering memory architecture established (`context.md`, `memory.md`).
- [x] Synthetic geomorphological DEM & terrain derivative generator (`elevation`, `slope`, `aspect`, `curvature`, `TRI`, `TWI`, `drainage`).
- [x] Vector infrastructure generator (NH-29 Highway, rural settlements, bridges, sensors, rivers).
- [x] Spatial Risk & Exposure Prioritization Engine ($R \times I$).
- [x] PostGIS schema DDL & SQLite/GeoPackage spatial indexing.
- [x] 2D Interactive Multi-Layer GIS Map (Leaflet).
- [x] 3D Digital Twin Terrain Mesh Viewer with real-time draped risk heatmaps (Three.js WebGL).
- [x] Standalone interactive V1 showcase (`dist/index.html`) & evaluation benchmark report (`docs/GIS_EVALUATION_REPORT.md`).

---

## 9. How to Reproduce V1

### Step 1: Environment Verification
Python 3.10+ with standard data science packages (`numpy`, `scipy`, `pandas`).
```bash
python -c "import numpy, scipy, pandas; print('Environment OK')"
```

### Step 2: Run End-to-End GIS Pipeline
Executes DEM synthesis, derivative calculation, vector generation, multi-temporal risk simulation, PostGIS DDL generation, and dashboard payload export:
```bash
python src/run_gis_pipeline.py
```

### Step 3: Build Standalone 2D/3D WebGL Digital Twin Dashboard
Compiles the self-contained HTML bundle (`dist/index.html`):
```bash
python src/build_dashboard.py
```

### Step 4: Open & Interact with the V1 Prototype
Open [dist/index.html](file:///d:/ANTIGRAVITY%20KA%20FOLDER/SIH/dist/index.html) directly in any modern browser.
- Toggle between **3D Terrain Digital Twin** and **2D GIS Multi-Layer Map**.
- Switch raster layers (DEM Elevation, Slope gradient, Topographic Wetness, Ruggedness).
- Scrub the **Monsoon Progression Slider** ($T+0\text{h} \to T+72\text{h}$) to see live dynamic risk heatmaps and priority action rankings.
- Click on any road sector, bridge, village, or sensor pin to inspect real-time attributes.
- Click **Export JSON** in the right panel to download structured evacuation and resource dispatch orders.
