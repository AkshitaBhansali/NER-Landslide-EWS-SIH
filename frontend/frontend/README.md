# NER Landslide Early Warning System — Frontend

Authority-facing web console for **SIH PS 26001 — AI-Based Early Warning and Landslide Risk Monitoring System in the North Eastern Region**, Ministry of Development of North Eastern Region (MDoNER).

This repository is the **frontend only**. It runs entirely on synthetic data today and is written so that the mock data layer can be swapped for the team's real backend without touching a single component.

> **Demo build.** Every district, sensor, reading, alert, incident and report in this app is generated. Nothing here is an official government warning, and the console has no authority to issue one.

---

## Running it

Requires Node 18 or newer.

```bash
npm install
npm run dev        # http://localhost:5173
```

Other scripts:

```bash
npm run build      # type-check + production build into dist/
npm run preview    # serve the built bundle on :4173
npm run typecheck  # tsc --noEmit
```

The build is routed with `HashRouter` and uses a relative `base`, so `dist/` can be served from any static folder or sub-path without server rewrite rules. That matters for the deployment target: district offices on intermittent links, where the console has to open from a laptop or a cheap static host.

No map SDK, no chart library, no CSS framework. The whole UI is React + TypeScript + hand-written SVG, which keeps the bundle around 100 kB gzipped and fully functional offline.

---

## Routes

| Route | Page | Owner it serves |
|---|---|---|
| `/` | Overview — KPIs, live map, pipeline strip, risk-vs-rainfall trend, road connectivity | whole team |
| `/live` | Live Monitoring — regional risk status, live environmental conditions, sensor cards | Saksham, Eisa |
| `/alerts` | Risk & Alerts — critical banner, severity tabs, filters, alert cards, detail drawer | Krish Modi (alert engine) |
| `/gis` | GIS Intelligence — 2D map, layer control, DEM/terrain panel, 3D terrain, infrastructure exposure | Ayush |
| `/sensors` | Sensor Network — fleet KPIs, health donut, sortable table, sensor drawer | Eisa |
| `/field-reports` | Field Reports — citizen/field submission form, media upload, offline queue | Akshita |
| `/incidents` | Incident History — table / timeline / map views, filters | Nitin |
| `/reports` | Reports & Analytics — quarterly report, charts, model performance, export | Nitin |
| `/settings` | Settings — thresholds, notification routing, language, offline behaviour | — |

Unknown routes redirect to `/`.

---

## Structure

```
src/
├── types/index.ts          One domain contract for the whole app. Mirrors the Python
│                           schemas in the data pipeline (see INTEGRATION.md).
├── data/mock/              The ONLY place demo data exists.
│   ├── regions.ts          8 NER states, 30 districts, coordinates, terrain class
│   ├── generator.ts        Deterministic seeded generator — zones, sensors, alerts,
│   │                       roads, villages, infrastructure, incidents, weather
│   ├── gis.ts              Layer registry + DEM grids
│   ├── reports.ts          Quarterly report builder + model metrics
│   └── alerts.ts sensors.ts weather.ts incidents.ts notifications.ts districts.ts
├── services/               The seam between UI and backend.
│   ├── api.ts              DATA_SOURCE switch, endpoint contract, fetch wrapper
│   ├── adapters.ts         snake_case → camelCase mapping
│   └── riskService alertService sensorService gisService incidentService
│       weatherService reportService systemService
├── state/
│   ├── AppContext.tsx      Region/district scope, connection, notifications, toasts
│   └── useAsync.ts         loading / error / empty / data hook
├── components/
│   ├── ui/                 Icons + primitives (Card, KpiCard, Drawer, AsyncSection…)
│   ├── charts/             SVG line, bar, donut, horizontal bar, calendar, sparkline
│   ├── map/                projection.ts, RiskMap, MapPanels, Terrain3D
│   ├── layout/             DashboardLayout (sidebar, topbar, nav), PageHeader
│   └── alerts/ sensors/ weather/ fieldreports/
├── pages/                  One file per route
└── styles/                 tokens.css → base.css → components.css
```

No page imports from `data/mock` for display data. Pages call services; services decide where data comes from.

---

## Design

The palette, typography and section language come from the sample quarterly risk report supplied with the brief — paper `#f7f5ef`, deep green `#0f5a52`, the four risk colours, Fraunces / Inter / IBM Plex Mono. The console chrome (sidebar, top bar) is the dark ink `#16211f`, so the shell reads as an operations centre while the content area reads as the printed report it produces.

Risk level is **never encoded by colour alone**: every risk badge carries a shape glyph and the word (`▲▲ CRITICAL`, `▲ HIGH`, `◆ MODERATE`, `● LOW`). Sensor status, sync status and road status follow the same rule.

Touch targets on mobile are 42 px; the sidebar becomes a drawer and a five-item bottom nav appears; the zone and sensor drawers become bottom sheets. Reduced-motion preferences disable the critical-zone pulse.

---

## Data honesty

- Everything synthetic is labelled. Cards carry a **Demo data** tag, the top bar carries a **DEMO DATA** chip, and the report cover and zone panels carry an explicit disclaimer.
- The model figures shown (Random Forest ROC-AUC 0.786, recall 0.850, precision 0.549) are the pipeline's **training** results on physics-simulated scenarios. Every place they appear, they are labelled as a baseline and not as validated field accuracy.
- The 95 mm / 24 h rainfall threshold is a demo operating figure, not a published standard.
- GIS layers that are not yet served (DEM tiles, satellite imagery) render as disabled toggles with a reason, rather than as buttons that do nothing.

---

## Known limitations

1. **No backend.** All writes — acknowledging an alert, dispatching a response, submitting a field report, saving settings — live in browser memory and are lost on refresh.
2. **Field report media is not uploaded.** Files are previewed from object URLs and counted, never transmitted.
3. **PDF export uses the browser print dialogue.** There is no server-side renderer; print styles are tuned so the output is usable.
4. **Map geometry is illustrative.** District centroids and boundaries are approximations for a demo projection, not survey data. Real GeoJSON replaces `components/map/projection.ts` consumers.
5. **DEM grid is procedurally generated.** It shows the intended terrain panel; it is not real elevation.
6. **3D terrain is a rendered approximation**, not a Cesium/deck.gl scene.
7. **Only English strings ship.** The language selector defines where a translation layer plugs in.
8. **No authentication or roles.** The user chip is decorative.
9. **Sensor readings are simulated** from the zone state; there is no live ingest.
10. **Offline support is “the app works with no network”**, not a service worker with background sync.

See `INTEGRATION.md` for exactly how each teammate's work plugs into this.
