import { useMemo, useState } from "react";
import type { GISLayerId, Infrastructure, RiskLevel } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { gisService, incidentService, riskService, sensorService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, RiskBadge } from "@/components/ui/primitives";
import { RiskMap, type MapSelection } from "@/components/map/RiskMap";
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

const DEFAULT_LAYERS: GISLayerId[] = ["risk_heatmap", "roads", "sensors", "settlements", "incidents"];

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

  const scopeDeps = [app.stateCode, app.districtId];
  const zones = useAsync(() => riskService.getRiskZones(app.scope), scopeDeps);
  const sensors = useAsync(() => sensorService.getSensors(app.scope), scopeDeps);
  const roads = useAsync(() => gisService.getRoads(app.scope), scopeDeps);
  const villages = useAsync(() => gisService.getVillages(app.scope), scopeDeps);
  const infra = useAsync(() => gisService.getInfrastructure(app.scope), scopeDeps);
  const incidents = useAsync(() => incidentService.getIncidents(app.scope), scopeDeps);
  const layerRegistry = useAsync(() => gisService.getLayers(), []);
  const corridor = useAsync(() => gisService.getCorridor(timestep), [timestep]);

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

  const onSelect = (sel: MapSelection) => {
    setSelection(sel);
    const zone = (zones.data ?? []).find((z) => z.id === sel.id);
    if (zone) setPoint(zone.center);
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

        {/* map */}
        <div className="grid grid-main">
          <section className="card">
            <header className="card-head">
              <div>
                <h2>Operational map</h2>
                <div className="hint">Select a zone to see what is exposed there</div>
              </div>
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
            </header>
            <div className="card-body">
              <AsyncSection state={zones} loadingLabel="Loading spatial risk…" rows={3}>
                {(list) => (
                  <RiskMap
                    zones={visibleZones.length ? visibleZones : list}
                    sensors={sensors.data ?? []}
                    roads={roads.data ?? []}
                    villages={villages.data ?? []}
                    infrastructure={infra.data ?? []}
                    incidents={incidents.data ?? []}
                    activeLayers={layers}
                    selected={selection}
                    onSelect={onSelect}
                    height={460}
                    showStateLabels
                  />
                )}
              </AsyncSection>
            </div>
          </section>

          {/* selected-point detail */}
          <Card
            title="Selected area"
            subtitle={point ? "Risk, sensors and exposure at this point" : undefined}
          >
            {!point ? (
              <EmptyState
                title="No area selected"
                hint="Select a risk zone on the map to see its score, the sensors reporting it, and the roads, settlements and infrastructure within 3 km."
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
