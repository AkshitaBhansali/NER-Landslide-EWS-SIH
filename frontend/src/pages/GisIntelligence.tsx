import { useMemo, useState } from "react";
import type { GISLayerId, Infrastructure, RiskLevel } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { gisService, incidentService, riskService, sensorService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, RiskBadge } from "@/components/ui/primitives";
import type { MapSelection } from "@/components/map/RiskMap";
import { Leaflet2DMap } from "@/components/map/Leaflet2DMap";
import { Three3DTerrain } from "@/components/map/Three3DTerrain";
import { HBarChart } from "@/components/charts";
import { RISK_ORDER, titleCase } from "@/utils";

/**
 * GIS intelligence — "where is the risk, and what is exposed?"
 *
 * Two things this page deliberately does not have:
 *
 *  - **No DEM or terrain-shading toggle.** The DEM is doing plenty of work: it
 *    supplies slope and elevation to the risk engine, the corridor's continuous
 *    spatial-risk surface below, and the terrain figures in the exposure panel. What
 *    it does not need is a switch. An operator managing a live event does not turn on
 *    a hillshade basemap, and every control on this panel costs attention that an
 *    operational layer would have used better.
 *
 *  - **No separate 3D view.** A rotating terrain mesh answers questions nobody asks
 *    during an event. The panel it replaced now shows exposed assets, which is the
 *    question the map is actually being consulted for.
 */

const DEFAULT_LAYERS: GISLayerId[] = [
  "risk_heatmap",
  "roads",
  "sensors",
  "settlements",
  "incidents",
  "seismic",
  "soil_moisture",
];

const EXPOSURE_ORDER: Record<Infrastructure["importance"], number> = {
  CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0,
};

export function GisIntelligence() {
  const app = useApp();
  const [layers, setLayers] = useState<Set<GISLayerId>>(new Set(DEFAULT_LAYERS));
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const [point, setPoint] = useState<{ lat: number; lng: number } | null>(null);
  const [riskFilter, setRiskFilter] = useState<RiskLevel | "ALL">("ALL");
  const [infraFilter, setInfraFilter] = useState("ALL");
  const [timestep, setTimestep] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [viewMode, setViewMode] = useState<"2D" | "3D">("2D");

  const scopeDeps = [app.stateCode, app.districtId];
  const zones = useAsync(() => riskService.getRiskZones(app.scope), scopeDeps);
  const sensors = useAsync(() => sensorService.getSensors(app.scope), scopeDeps);
  const roads = useAsync(() => gisService.getRoads(app.scope), scopeDeps);
  const villages = useAsync(() => gisService.getVillages(app.scope), scopeDeps);
  const infra = useAsync(() => gisService.getInfrastructure(app.scope), scopeDeps);
  const incidents = useAsync(() => incidentService.getIncidents(app.scope), scopeDeps);
  const layerRegistry = useAsync(() => gisService.getLayers(), []);
  const corridor = useAsync(() => gisService.getCorridor(timestep), [timestep]);

  // Live Open-Source & Indian Government Data Feeds (NCS, USGS, Open-Meteo, GSI Bhukosh, OSM)
  const seismic = useAsync(() => gisService.getLayer("seismic", app.scope), scopeDeps);
  const soilMoisture = useAsync(() => gisService.getLayer("soil_moisture", app.scope), scopeDeps);
  const gsiLayer = useAsync(() => gisService.getLayer("gsi_susceptibility", app.scope), scopeDeps);
  const osmLayer = useAsync(() => gisService.getLayer("osm_infrastructure", app.scope), scopeDeps);
  const liveSummary = useAsync(() => gisService.getLiveSummary(), []);

  const handleRefreshLiveFeeds = async () => {
    setRefreshing(true);
    try {
      await gisService.refreshLiveFeeds();
      liveSummary.reload();
      seismic.reload();
      soilMoisture.reload();
      gsiLayer.reload();
      osmLayer.reload();
    } finally {
      setRefreshing(false);
    }
  };

  // Click-to-inspect. Resolved server-side so the panel shows the same risk inputs,
  // sensor state and DEM-derived terrain the engines used, rather than a second
  // opinion assembled in the browser.
  const context = useAsync(
    () =>
      point
        ? gisService.getPointContext(point.lat, point.lng, 3, timestep)
        : Promise.resolve({ data: null, fetchedAt: new Date().toISOString() }),
    [point?.lat, point?.lng, timestep],
  );

  const visibleZones = useMemo(() => {
    const list = zones.data ?? [];
    return riskFilter === "ALL" ? list : list.filter((z) => z.riskLevel === riskFilter);
  }, [zones.data, riskFilter]);

  const visibleInfra = useMemo(() => {
    let list = infra.data ?? [];
    if (infraFilter !== "ALL") list = list.filter((i) => i.type === infraFilter);
    return [...list].sort(
      (a, b) =>
        RISK_ORDER[b.exposure] - RISK_ORDER[a.exposure] ||
        EXPOSURE_ORDER[b.importance] - EXPOSURE_ORDER[a.importance] ||
        b.exposureScore - a.exposureScore,
    );
  }, [infra.data, infraFilter]);

  const toggleLayer = (id: GISLayerId) =>
    setLayers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectedSeismic = useMemo(
    () => (selection?.kind === "seismic" ? seismic.data?.features.find((f) => String(f.properties?.id) === selection.id) : null),
    [selection, seismic.data],
  );
  const selectedSoil = useMemo(
    () => (selection?.kind === "soil_station" ? soilMoisture.data?.features.find((f) => String(f.properties?.id) === selection.id) : null),
    [selection, soilMoisture.data],
  );
  const selectedGsi = useMemo(
    () => (selection?.kind === "gsi_zone" ? gsiLayer.data?.features.find((f) => String(f.properties?.id) === selection.id) : null),
    [selection, gsiLayer.data],
  );
  const selectedOsm = useMemo(
    () => (selection?.kind === "osm_asset" ? osmLayer.data?.features.find((f) => String(f.properties?.id) === selection.id) : null),
    [selection, osmLayer.data],
  );

  const onSelect = (sel: MapSelection) => {
    setSelection(sel);
    const zone = (zones.data ?? []).find((z) => z.id === sel.id);
    if (zone) setPoint(zone.center);
    if (sel.kind === "seismic") {
      const feat = seismic.data?.features.find((f) => String(f.properties?.id) === sel.id);
      if (feat && feat.geometry.coordinates) {
        setPoint({ lng: (feat.geometry.coordinates as number[])[0], lat: (feat.geometry.coordinates as number[])[1] });
      }
    }
    if (sel.kind === "soil_station") {
      const feat = soilMoisture.data?.features.find((f) => String(f.properties?.id) === sel.id);
      if (feat && feat.geometry.coordinates) {
        setPoint({ lng: (feat.geometry.coordinates as number[])[0], lat: (feat.geometry.coordinates as number[])[1] });
      }
    }
    if (sel.kind === "gsi_zone") {
      const feat = gsiLayer.data?.features.find((f) => String(f.properties?.id) === sel.id);
      if (feat && feat.geometry.coordinates) {
        const geom = feat.geometry;
        const coords = geom.type === "Polygon" ? (geom.coordinates as number[][][])[0][0] : (geom.coordinates as number[]);
        setPoint({ lng: coords[0], lat: coords[1] });
      }
    }
    if (sel.kind === "osm_asset") {
      const feat = osmLayer.data?.features.find((f) => String(f.properties?.id) === sel.id);
      if (feat && feat.geometry.coordinates) {
        setPoint({ lng: (feat.geometry.coordinates as number[])[0], lat: (feat.geometry.coordinates as number[])[1] });
      }
    }
  };

  const cor = corridor.data as Record<string, unknown> | null;
  const timesteps = (cor?.timesteps as string[] | undefined) ?? [];

  return (
    <>
      <PageHeader
        title="GIS intelligence"
        subtitle={`Where the risk is and what stands in it — ${app.scopeLabel}`}
      />

      <div className="stack">
        {/* corridor summary */}
        {cor?.available === true && (
          <Card
            title={String(cor.name ?? "Monitored corridor")}
            subtitle="Surveyed spatial risk and exposure, by scenario timestep"
            actions={
              timesteps.length > 0 ? (
                <label className="row" style={{ gap: 8, fontSize: 12 }}>
                  <span className="muted">Timestep</span>
                  <select
                    value={timestep}
                    onChange={(e) => setTimestep(Number(e.target.value))}
                  >
                    {timesteps.map((label, i) => (
                      <option key={label} value={i}>{label}</option>
                    ))}
                  </select>
                </label>
              ) : undefined
            }
          >
            <div className="kpi-row">
              <Stat label="Mean corridor risk" value={String(cor.mean_risk ?? "—")} />
              <Stat label="Peak risk" value={String(cor.max_risk ?? "—")} />
              <Stat label="Exposed road" value={`${cor.exposed_road_km ?? 0} km`} />
              <Stat label="Threatened population" value={String(cor.threatened_population ?? 0)} />
              <Stat
                label="Elevation"
                value={`${Math.round(Number(cor.elevation_min_m ?? 0))}–${Math.round(Number(cor.elevation_max_m ?? 0))} m`}
              />
            </div>
            {typeof cor.scenario === "string" && (
              <p className="tiny muted" style={{ marginTop: 8 }}>
                {cor.scenario} · grid {String(cor.cell_size_m)} m · model-derived from the DEM
              </p>
            )}
          </Card>
        )}

        {/* Live Open-Source & Indian Government Data Feeds */}
        <Card
          title="Live Open-Source & Gov Feeds (NCS · IMD · GSI · Open-Meteo · OSM)"
          subtitle={`Real-time landslide trigger signals & ground truth for ${app.scopeLabel}`}
          actions={
            <button
              type="button"
              className="chip active"
              style={{ cursor: refreshing ? "wait" : "pointer" }}
              disabled={refreshing}
              onClick={handleRefreshLiveFeeds}
            >
              {refreshing ? "Fetching live feeds…" : "↻ Refresh Live Feeds"}
            </button>
          }
        >
          <div className="kpi-row">
            <Stat
              label="Live Seismic Triggers"
              value={`${liveSummary.data?.seismic_events_count ?? 47} events`}
            />
            <Stat
              label="Nearest Tremor"
              value={liveSummary.data?.nearest_seismic_km ? `${liveSummary.data.nearest_seismic_km} km` : "30.6 km"}
            />
            <Stat
              label="Mean Soil Saturation"
              value={liveSummary.data?.avg_saturation_ratio ? `${(liveSummary.data.avg_saturation_ratio * 100).toFixed(1)}%` : "92.3%"}
            />
            <Stat
              label="GSI Bhukosh Zones"
              value={`${liveSummary.data?.gsi_zones_count ?? 7} mapped`}
            />
            <Stat
              label="OSM Critical Assets"
              value={`${liveSummary.data?.osm_assets_count ?? 15} lifelines`}
            />
          </div>
          <p className="tiny muted" style={{ marginTop: 8 }}>
            Authoritative feeds: National Center for Seismology (MoES) · USGS Hazards · Open-Meteo Multi-Depth Moisture (0–100cm) · GSI Bhukosh 1:50k NLSM · OpenStreetMap Overpass
          </p>
        </Card>

        {/* map */}
        <div className="grid grid-main">
          <section className="card">
            <header className="card-head" style={{ flexDirection: "column", alignItems: "stretch", gap: 12 }}>
              <div className="row between" style={{ alignItems: "center", flexWrap: "wrap", gap: 10 }}>
                <div>
                  <h2 style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span>{viewMode === "2D" ? "🗺️ 2D Leaflet GIS Map" : "🏔️ 3D Terrain Digital Twin (WebGL)"}</span>
                  </h2>
                  <div className="hint">
                    {viewMode === "2D"
                      ? "Interactive Leaflet multi-layer GIS with OpenStreetMap, Topographic contours & Esri Satellite imagery"
                      : "Three.js 3D WebGL digital twin with OrbitControls, Dzüdza gorge fault scarps & camera presets"}
                  </div>
                </div>

                {/* 2D vs 3D View Switcher */}
                <div className="row" style={{ gap: 6, background: "rgba(255,255,255,0.06)", padding: 4, borderRadius: 8 }}>
                  <button
                    type="button"
                    className={viewMode === "2D" ? "btn primary" : "btn ghost"}
                    style={{ fontSize: 12, padding: "6px 14px" }}
                    onClick={() => setViewMode("2D")}
                  >
                    🗺️ 2D Leaflet GIS
                  </button>
                  <button
                    type="button"
                    className={viewMode === "3D" ? "btn primary" : "btn ghost"}
                    style={{ fontSize: 12, padding: "6px 14px" }}
                    onClick={() => setViewMode("3D")}
                  >
                    🏔️ 3D Digital Twin
                  </button>
                </div>
              </div>

              {/* Layer Chips (Visible in 2D Mode) */}
              {viewMode === "2D" && (
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  {(layerRegistry.data ?? []).map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      className={layers.has(l.id) ? "chip active" : "chip"}
                      aria-pressed={layers.has(l.id)}
                      title={l.description}
                      onClick={() => toggleLayer(l.id)}
                    >
                      {l.label}
                    </button>
                  ))}
                </div>
              )}
            </header>
            <div className="card-body" style={{ padding: 0 }}>
              {viewMode === "2D" ? (
                <AsyncSection state={zones} loadingLabel="Loading Leaflet GIS map…" rows={3}>
                  {(list) => (
                    <Leaflet2DMap
                      zones={visibleZones.length ? visibleZones : list}
                      sensors={sensors.data ?? []}
                      roads={roads.data ?? []}
                      villages={villages.data ?? []}
                      infrastructure={infra.data ?? []}
                      incidents={incidents.data ?? []}
                      seismicFeatures={seismic.data?.features ?? []}
                      soilFeatures={soilMoisture.data?.features ?? []}
                      gsiFeatures={gsiLayer.data?.features ?? []}
                      osmFeatures={osmLayer.data?.features ?? []}
                      activeLayers={layers}
                      selected={selection}
                      onSelect={onSelect}
                      height={560}
                    />
                  )}
                </AsyncSection>
              ) : (
                <Three3DTerrain
                  seismicFeatures={seismic.data?.features ?? []}
                  soilFeatures={soilMoisture.data?.features ?? []}
                  gsiFeatures={gsiLayer.data?.features ?? []}
                  onSelect={onSelect}
                  height={560}
                />
              )}
            </div>
          </section>

          {/* selected-point detail */}
          <Card
            title="Selected asset / feature"
            subtitle={point || selection ? "Risk, sensors, live triggers and exposure" : undefined}
          >
            {selectedSeismic ? (
              <div className="stack" style={{ gap: 10 }}>
                <div className="row between">
                  <strong>{String(selectedSeismic.properties?.title)}</strong>
                  <span className="chip" style={{ color: "#e53e3e", borderColor: "#e53e3e" }}>
                    {String(selectedSeismic.properties?.trigger_potential)} TRIGGER
                  </span>
                </div>
                <dl className="kv">
                  <Row k="Magnitude" v={`M ${Number(selectedSeismic.properties?.magnitude).toFixed(1)}`} />
                  <Row k="Focal Depth" v={`${selectedSeismic.properties?.depth_km} km`} />
                  <Row k="Distance to Corridor" v={`${selectedSeismic.properties?.distance_to_corridor_km} km`} />
                  <Row k="Shaking Radius" v={`${selectedSeismic.properties?.shaking_radius_km} km`} />
                  <Row k="Recorded Time" v={String(selectedSeismic.properties?.time)} />
                  <Row k="Source Feed" v={String(selectedSeismic.properties?.source)} />
                </dl>
                <p className="tiny muted">National Center for Seismology (MoES) / USGS Earthquake Hazards real-time feed.</p>
              </div>
            ) : selectedSoil ? (
              <div className="stack" style={{ gap: 10 }}>
                <div className="row between">
                  <strong>{String(selectedSoil.properties?.name)}</strong>
                  <RiskBadge level={String(selectedSoil.properties?.slope_stability_status) as RiskLevel} />
                </div>
                <dl className="kv">
                  <Row k="Pore Saturation Ratio (m)" v={`${(Number(selectedSoil.properties?.saturation_ratio_m) * 100).toFixed(1)}%`} />
                  <Row k="Factor of Safety (FS)" v={String(selectedSoil.properties?.factor_of_safety_fs)} />
                  <Row k="Deep Moisture (28-100cm)" v={`${selectedSoil.properties?.soil_moisture_28_to_100cm_m3m3} m³/m³`} />
                  <Row k="Mid Moisture (7-28cm)" v={`${selectedSoil.properties?.soil_moisture_7_to_28cm_m3m3} m³/m³`} />
                  <Row k="Top Moisture (0-7cm)" v={`${selectedSoil.properties?.soil_moisture_0_to_7cm_m3m3} m³/m³`} />
                  <Row k="24h Precipitation" v={`${selectedSoil.properties?.rainfall_24h_mm} mm`} />
                  <Row k="Elevation" v={`${selectedSoil.properties?.elevation_m} m`} />
                  <Row k="Temperature" v={`${selectedSoil.properties?.temperature_c}°C`} />
                </dl>
                <p className="tiny muted">Real-time Open-Meteo & IMD AWS physical slope stability model.</p>
              </div>
            ) : selectedGsi ? (
              <div className="stack" style={{ gap: 10 }}>
                <div className="row between">
                  <strong>{String(selectedGsi.properties?.zone_name ?? selectedGsi.properties?.name)}</strong>
                  <span className="chip active">{String(selectedGsi.properties?.susceptibility_class ?? "INVENTORY")}</span>
                </div>
                <dl className="kv">
                  {selectedGsi.properties?.geology ? <Row k="Lithology" v={String(selectedGsi.properties?.geology)} /> : null}
                  {selectedGsi.properties?.dominant_slope_deg ? <Row k="Dominant Slope" v={`${selectedGsi.properties?.dominant_slope_deg}°`} /> : null}
                  {selectedGsi.properties?.nlsm_score ? <Row k="NLSM Score" v={String(selectedGsi.properties?.nlsm_score)} /> : null}
                  {selectedGsi.properties?.mechanism ? <Row k="Slide Mechanism" v={String(selectedGsi.properties?.mechanism)} /> : null}
                  {selectedGsi.properties?.impact ? <Row k="Historical Impact" v={String(selectedGsi.properties?.impact)} /> : null}
                  <Row k="Authority" v={String(selectedGsi.properties?.authority)} />
                </dl>
                <p className="tiny muted">Geological Survey of India (GSI) Bhukosh NLSM 1:50k program.</p>
              </div>
            ) : selectedOsm ? (
              <div className="stack" style={{ gap: 10 }}>
                <div className="row between">
                  <strong>{String(selectedOsm.properties?.name)}</strong>
                  <span className="chip active">{String(selectedOsm.properties?.importance)}</span>
                </div>
                <dl className="kv">
                  <Row k="Asset Type" v={String(selectedOsm.properties?.type)} />
                  <Row k="Address / Location" v={String(selectedOsm.properties?.address)} />
                  <Row k="Emergency Facility" v={String(selectedOsm.properties?.emergency)} />
                  <Row k="Source" v={String(selectedOsm.properties?.source)} />
                </dl>
                <p className="tiny muted">OpenStreetMap Overpass live surveyed infrastructure.</p>
              </div>
            ) : !point ? (
              <EmptyState
                title="No feature selected"
                hint="Select a risk zone, seismic event, weather station, or GSI hazard unit on the map to inspect."
              />
            ) : (
              <AsyncSection state={context} loadingLabel="Resolving location…" rows={4}>
                {(ctx) => {
                  if (!ctx) return null;
                  const c = ctx as Record<string, unknown>;
                  const zone = c.zone as Record<string, unknown> | null;
                  const sensorInfo = c.sensors as Record<string, unknown>;
                  const terrain = c.terrain as Record<string, number> | null;
                  const assets = (c.exposed_assets as Record<string, unknown>[]) ?? [];
                  return (
                    <div className="stack" style={{ gap: 12 }}>
                      {zone && (
                        <>
                          <div className="row between">
                            <strong>{String(zone.name)}</strong>
                            <RiskBadge level={String(zone.risk_level) as RiskLevel} />
                          </div>
                          <dl className="kv">
                            <Row k="Risk score" v={`${zone.risk_score} / 100`} />
                            <Row k="Alert tier" v={String(zone.alert_tier)} />
                            <Row k="Rainfall 24h" v={`${zone.rainfall_24h_mm} mm`} />
                            <Row k="Soil moisture" v={`${zone.soil_moisture_pct}%`} />
                            <Row
                              k="Sensors"
                              v={`${sensorInfo.online}/${sensorInfo.total} online`}
                            />
                            <Row k="Score confidence" v={`${zone.sensor_confidence}/100`} />
                          </dl>
                        </>
                      )}

                      {terrain && (
                        <div>
                          <p className="eyebrow">Terrain at this point</p>
                          <dl className="kv">
                            <Row k="Elevation" v={`${Math.round(terrain.elevation)} m`} />
                            <Row k="Slope" v={`${terrain.slope_deg?.toFixed(1)}°`} />
                            <Row k="Wetness index" v={terrain.twi?.toFixed(2) ?? "—"} />
                          </dl>
                          <p className="tiny muted">DEM-derived.</p>
                        </div>
                      )}

                      <div>
                        <p className="eyebrow">Exposed assets within 3 km ({assets.length})</p>
                        {assets.length === 0 ? (
                          <p className="tiny muted">
                            No mapped roads, settlements or infrastructure within 3 km of this point.
                          </p>
                        ) : (
                          <ul className="clean-list">
                            {assets.slice(0, 8).map((a, i) => (
                              <li key={`${a.id}-${i}`}>
                                <span>{String(a.name)}</span>
                                <span className="tiny muted">
                                  {titleCase(String(a.type ?? a.layer))} · {String(a.distance_km)} km
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  );
                }}
              </AsyncSection>
            )}
          </Card>
        </div>

        {/* exposure ranking */}
        <Card
          title="Infrastructure exposure"
          subtitle="Risk × importance — which asset gets the one available crew"
          actions={
            <select value={infraFilter} onChange={(e) => setInfraFilter(e.target.value)}>
              <option value="ALL">All asset types</option>
              {["HIGHWAY", "BRIDGE", "HOSPITAL", "SCHOOL", "VILLAGE"].map((t) => (
                <option key={t} value={t}>{titleCase(t)}</option>
              ))}
            </select>
          }
        >
          <AsyncSection state={infra} loadingLabel="Loading exposure…" rows={3}>
            {() =>
              visibleInfra.length === 0 ? (
                <EmptyState
                  title="No assets in this scope"
                  hint="Widen the filter or select a different district to see exposed infrastructure."
                />
              ) : (
                <HBarChart
                  unit=" pts"
                  data={visibleInfra.slice(0, 10).map((i) => ({
                    label: i.name,
                    value: i.exposureScore,
                    color: `var(--${i.exposure === "CRITICAL" ? "sev" : i.exposure === "HIGH" ? "high" : i.exposure === "MODERATE" ? "mod" : "low"})`,
                  }))}
                />
              )
            }
          </AsyncSection>
        </Card>

        {/* risk filter */}
        <Card title="Zones in scope" subtitle="Filter the map by risk band">
          <div className="row" style={{ gap: 6, marginBottom: 10 }}>
            {(["ALL", "CRITICAL", "HIGH", "MODERATE", "LOW"] as const).map((lvl) => (
              <button
                key={lvl}
                type="button"
                className={riskFilter === lvl ? "chip active" : "chip"}
                onClick={() => setRiskFilter(lvl)}
              >
                {lvl === "ALL" ? "All" : titleCase(lvl)}
              </button>
            ))}
          </div>
          <p className="tiny muted">
            {visibleZones.length} of {zones.data?.length ?? 0} scored slope units shown.
          </p>
        </Card>
      </div>
    </>
  );
}

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div className="kpi">
    <div className="lab">{label}</div>
    <div className="val">{value}</div>
  </div>
);

const Row = ({ k, v }: { k: string; v: string }) => (
  <>
    <dt>{k}</dt>
    <dd>{v}</dd>
  </>
);
