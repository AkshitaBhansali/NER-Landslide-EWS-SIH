# Standalone 2D/3D corridor viewer

`index.html` is the GIS workstream's self-contained digital-twin viewer for the
Kohima–Dimapur corridor. Open it directly in a browser — no build step, no server:

```
gis/viewer/index.html
```

It carries its own copy of the corridor payload inline (~817 KB of embedded
`DASHBOARD_DATA`), so it renders terrain, risk surfaces, roads, settlements, rivers,
critical assets and sensors with no backend running. Three.js, Leaflet and Lucide
load from CDNs, so the 3D terrain view needs an internet connection; the rest of the
page works offline.

## Why it is kept separate from the console

The platform console (`frontend/`) reads live state from the API and is the surface
an operator actually works in. This viewer is a frozen snapshot: it cannot show a
current alert, a live sensor reading or a verified incident, because its data was
baked in when the GIS pipeline last ran.

They answer different questions, so both are kept. Use the console for operations;
use this to inspect the corridor's terrain and exposure modelling on its own, or to
demonstrate the GIS work without standing up the backend.

Regenerate it by re-running the pipeline:

```bash
cd gis && python src/run_gis_pipeline.py && python src/build_dashboard.py
```

Note that it lives in `viewer/`, not `dist/`. Packaging excludes `dist/` as build
output, and this file is a deliverable rather than a rebuildable artifact — it was
lost from one release that way.
