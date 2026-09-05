import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type {
  GISLayerId,
  HistoricalIncident,
  Infrastructure,
  RiskZone,
  RoadStatus,
  Sensor,
  Village,
} from "@/types";

export interface MapSelection {
  kind:
    | "zone"
    | "sensor"
    | "road"
    | "incident"
    | "village"
    | "infrastructure"
    // Additional selection kinds used by the GIS Intelligence live-feed map
    // (Leaflet2DMap / Three3DTerrain). RiskMap itself never produces these,
    // so this widening does not change RiskMap's existing behavior anywhere
    // it's already used (e.g. Overview).
    | "seismic"
    | "soil_station"
    | "gsi_zone"
    | "osm_asset";
  id: string;
}

// Minimal GeoJSON feature shape for the live open-data layers (seismic,
// soil moisture, GSI susceptibility, OSM infrastructure) consumed by the
// GIS Intelligence page's map components.
export interface LiveGeoFeature {
  type: "Feature";
  geometry: { type: string; coordinates: any };
  properties: Record<string, unknown>;
}

interface Props {
  zones: RiskZone[];
  sensors?: Sensor[];
  roads?: RoadStatus[];
  villages?: Village[];
  infrastructure?: Infrastructure[];
  incidents?: HistoricalIncident[];
  activeLayers: Set<GISLayerId>;
  selected?: MapSelection | null;
  onSelect?: (sel: MapSelection) => void;
  height?: number | string;
  showStateLabels?: boolean;
}

const RISK_COLOR: Record<string, string> = {
  LOW: "#4a9d4a",
  MODERATE: "#e6a52a",
  HIGH: "#d1642e",
  CRITICAL: "#b5342e",
};

const ROAD_COLOR: Record<RoadStatus["status"], string> = {
  OPEN: "#5b6f6a",
  AT_RISK: "#e6a52a",
  RESTRICTED: "#d1642e",
  BLOCKED: "#b5342e",
};

const SENSOR_COLOR: Record<Sensor["status"], string> = {
  ONLINE: "#4a9d4a",
  DEGRADED: "#e6a52a",
  OFFLINE: "#b5342e",
};

const NER_BOUNDS = L.latLngBounds([22.0, 87.9], [28.6, 97.4]);

const TILE_CONFIGS = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    label: "OpenStreetMap tile layer",
  },
  satellite: {
    url: "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attribution: "&copy; Google Maps Satellite",
    label: "Satellite imagery tile layer",
  },
  terrain: {
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a> contributors',
    label: "Terrain contour tile layer",
  },
};

export function RiskMap({
  zones,
  sensors = [],
  roads = [],
  villages = [],
  infrastructure = [],
  incidents = [],
  activeLayers,
  selected,
  onSelect,
  height = "100%",
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const tileLayerRef = useRef<L.TileLayer | null>(null);
  const layersGroupRef = useRef<L.LayerGroup | null>(null);

  // 1. Initialize Map
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: true,
    }).fitBounds(NER_BOUNDS);

    const initialTileKey = activeLayers.has("satellite")
      ? "satellite"
      : activeLayers.has("terrain")
        ? "terrain"
        : "osm";

    const tileLayer = L.tileLayer(TILE_CONFIGS[initialTileKey].url, {
      maxZoom: 18,
      attribution: TILE_CONFIGS[initialTileKey].attribution,
    }).addTo(map);

    tileLayerRef.current = tileLayer;

    const layersGroup = L.layerGroup().addTo(map);
    mapRef.current = map;
    layersGroupRef.current = layersGroup;

    return () => {
      map.remove();
      mapRef.current = null;
      tileLayerRef.current = null;
      layersGroupRef.current = null;
    };
  }, []);

  // 2. Handle Base Tile Layer Switch (OSM vs Satellite vs Terrain)
  const isSatellite = activeLayers.has("satellite");
  const isTerrain = activeLayers.has("terrain");
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const targetKey = isSatellite ? "satellite" : isTerrain ? "terrain" : "osm";
    const targetConfig = TILE_CONFIGS[targetKey];

    if (tileLayerRef.current) {
      map.removeLayer(tileLayerRef.current);
    }

    tileLayerRef.current = L.tileLayer(targetConfig.url, {
      maxZoom: 18,
      attribution: targetConfig.attribution,
    }).addTo(map);
  }, [isSatellite, isTerrain]);

  // 3. Handle District Zoom / Auto-fit bounds
  const scopeKey = zones.map((z) => z.id).join(",");
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (zones.length === 0) {
      map.flyToBounds(NER_BOUNDS, { duration: 1.2 });
      return;
    }

    if (zones.length === 1) {
      const center = zones[0].center;
      map.flyTo([center.lat, center.lng], 12, { duration: 1 });
    } else {
      const lats = zones.map((z) => z.center.lat);
      const lngs = zones.map((z) => z.center.lng);
      const bounds = L.latLngBounds(
        [Math.min(...lats), Math.min(...lngs)],
        [Math.max(...lats), Math.max(...lngs)],
      );

      const isFullScope = zones.length > 20;

      if (isFullScope) {
        map.flyToBounds(NER_BOUNDS, { duration: 1, padding: [20, 20] });
      } else {
        map.flyToBounds(bounds, { duration: 1, padding: [40, 40], maxZoom: 13 });
      }
    }
  }, [scopeKey]);

  // 4. Render Data Layers
  useEffect(() => {
    const map = mapRef.current;
    const group = layersGroupRef.current;
    if (!map || !group) return;

    group.clearLayers();

    const isSel = (kind: MapSelection["kind"], id: string) =>
      selected?.kind === kind && selected?.id === id;

    // --- Layer: Rainfall Wash ---
    if (activeLayers.has("rainfall")) {
      zones.forEach((z) => {
        const radius = 3000 + (z.rainfall24h / 200) * 8000;
        L.circle([z.center.lat, z.center.lng], {
          radius,
          color: "#2f6f9e",
          fillColor: "#2f6f9e",
          fillOpacity: Math.min(0.35, 0.1 + z.rainfall24h / 500),
          weight: 1,
        }).addTo(group);
      });
    }

    // --- Layer: Risk Heatmap & Polygons ---
    if (activeLayers.has("risk_heatmap")) {
      zones.forEach((z) => {
        const color = RISK_COLOR[z.riskLevel] || "#4a9d4a";
        const heatRadius = 2500 + (z.riskScore / 100) * 6000;

        L.circle([z.center.lat, z.center.lng], {
          radius: heatRadius,
          color,
          fillColor: color,
          fillOpacity: 0.22,
          weight: 0,
        }).addTo(group);

        if (z.geometry && z.geometry.coordinates && z.geometry.coordinates[0]) {
          const latLngs: L.LatLngExpression[] = z.geometry.coordinates[0].map(
            ([lng, lat]) => [lat, lng],
          );
          const polygon = L.polygon(latLngs, {
            color,
            fillColor: color,
            fillOpacity: isSel("zone", z.id) ? 0.35 : 0.15,
            weight: isSel("zone", z.id) ? 3 : 1.5,
            dashArray: z.riskLevel === "CRITICAL" ? undefined : "4, 4",
          }).addTo(group);

          polygon.on("click", () => onSelect?.({ kind: "zone", id: z.id }));
        }
      });
    }

    // --- Layer: Roads ---
    if (activeLayers.has("roads")) {
      roads.forEach((r) => {
        const color = ROAD_COLOR[r.status];
        const latLngs: L.LatLngExpression[] = r.path.map(([lng, lat]) => [lat, lng]);
        const polyline = L.polyline(latLngs, {
          color,
          weight: isSel("road", r.id) ? 6 : r.status === "BLOCKED" ? 4.5 : 3.5,
          opacity: 0.85,
          dashArray: r.status === "BLOCKED" ? "8, 6" : undefined,
        }).addTo(group);

        polyline.bindTooltip(`<b>${r.name}</b><br/>Status: ${r.status}`, {
          sticky: true,
        });
        polyline.on("click", () => onSelect?.({ kind: "road", id: r.id }));
      });
    }

    // --- Layer: Settlements / Villages ---
    if (activeLayers.has("settlements")) {
      villages.forEach((v) => {
        const color = RISK_COLOR[v.riskLevel] || "#4a9d4a";
        const marker = L.circleMarker([v.location.lat, v.location.lng], {
          radius: isSel("village", v.id) ? 7 : 5,
          color: "#ffffff",
          fillColor: color,
          fillOpacity: 0.9,
          weight: 2,
        }).addTo(group);

        marker.bindTooltip(`Village: ${v.name} (${v.riskLevel})`);
        marker.on("click", () => onSelect?.({ kind: "village", id: v.id }));
      });
    }

    // --- Layer: Infrastructure ---
    if (activeLayers.has("infrastructure")) {
      infrastructure.forEach((inf) => {
        const color = RISK_COLOR[inf.exposure] || "#4a9d4a";
        const marker = L.circleMarker([inf.location.lat, inf.location.lng], {
          radius: isSel("infrastructure", inf.id) ? 8 : 6,
          color: "#333333",
          fillColor: color,
          fillOpacity: 0.95,
          weight: 2,
        }).addTo(group);

        marker.bindTooltip(`${inf.type}: ${inf.name} (Exposure: ${inf.exposure})`);
        marker.on("click", () => onSelect?.({ kind: "infrastructure", id: inf.id }));
      });
    }

    // --- Layer: Historical Incidents ---
    if (activeLayers.has("incidents")) {
      incidents.forEach((inc) => {
        const color = RISK_COLOR[inc.severity] || "#b5342e";
        const marker = L.circleMarker([inc.center.lat, inc.center.lng], {
          radius: isSel("incident", inc.id) ? 9 : 7,
          color: "#ffffff",
          fillColor: color,
          fillOpacity: 0.9,
          weight: 2,
        }).addTo(group);

        marker.bindTooltip(`Incident: ${inc.incidentType} (${inc.location})`);
        marker.on("click", () => onSelect?.({ kind: "incident", id: inc.id }));
      });
    }

    // --- Layer: Sensors ---
    if (activeLayers.has("sensors")) {
      sensors.forEach((s) => {
        const color = SENSOR_COLOR[s.status] || "#4a9d4a";
        const marker = L.circleMarker([s.location.lat, s.location.lng], {
          radius: isSel("sensor", s.id) ? 7 : 4.5,
          color: "#ffffff",
          fillColor: color,
          fillOpacity: 1,
          weight: 1.5,
        }).addTo(group);

        marker.bindTooltip(`Sensor ${s.id}: ${s.name} (${s.status})`);
        marker.on("click", () => onSelect?.({ kind: "sensor", id: s.id }));
      });
    }

    // --- Zone Centroid Markers (Always on map) ---
    zones.forEach((z) => {
      const color = RISK_COLOR[z.riskLevel] || "#4a9d4a";
      const selectedZone = isSel("zone", z.id);

      const icon = L.divIcon({
        className: "custom-zone-marker-wrapper",
        html: `
          <div class="zone-badge ${selectedZone ? "selected" : ""} ${z.riskLevel.toLowerCase()}" style="
            background-color: ${color};
            color: #ffffff;
            border: 2px solid #ffffff;
            border-radius: 12px;
            padding: 2px 7px;
            font-size: 11px;
            font-weight: 700;
            font-family: var(--font-mono, monospace);
            box-shadow: 0 2px 8px rgba(0,0,0,0.35);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            white-space: nowrap;
            cursor: pointer;
            transform: translate(-50%, -50%);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
          ">
            <span>${z.riskScore}</span>
          </div>
        `,
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });

      const marker = L.marker([z.center.lat, z.center.lng], { icon }).addTo(group);

      marker.bindTooltip(
        `<b>${z.name}</b><br/>District: ${z.district}<br/>Score: ${z.riskScore} (${z.riskLevel})`,
        { direction: "top", offset: [0, -10] },
      );

      marker.on("click", () => onSelect?.({ kind: "zone", id: z.id }));
    });
  }, [zones, sensors, roads, villages, infrastructure, incidents, activeLayers, selected, onSelect]);

  const tileInfo = isSatellite
    ? TILE_CONFIGS.satellite
    : isTerrain
      ? TILE_CONFIGS.terrain
      : TILE_CONFIGS.osm;

  return (
    <div className="map-frame" style={{ height }}>
      {/* Map Container */}
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />

      {/* Map Controls */}
      <div className="map-controls noprint">
        <button
          type="button"
          onClick={() => mapRef.current?.zoomIn()}
          aria-label="Zoom in"
          title="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => mapRef.current?.zoomOut()}
          aria-label="Zoom out"
          title="Zoom out"
        >
          −
        </button>
        <button
          type="button"
          onClick={() => {
            if (zones.length > 0 && zones.length <= 20) {
              const lats = zones.map((z) => z.center.lat);
              const lngs = zones.map((z) => z.center.lng);
              mapRef.current?.flyToBounds(
                L.latLngBounds(
                  [Math.min(...lats), Math.min(...lngs)],
                  [Math.max(...lats), Math.max(...lngs)],
                ),
                { padding: [40, 40], maxZoom: 13 },
              );
            } else {
              mapRef.current?.flyToBounds(NER_BOUNDS);
            }
          }}
          aria-label="Reset view"
          title="Reset view"
          style={{ fontSize: 11 }}
        >
          ⌂
        </button>
      </div>

      {/* Map Legend */}
      <MapLegend tileLabel={tileInfo.label} />
    </div>
  );
}

export function MapLegend({ tileLabel }: { tileLabel?: string }) {
  return (
    <div className="map-legend">
      <div className="eyebrow" style={{ marginBottom: 3 }}>
        Risk level
      </div>
      {(["LOW", "MODERATE", "HIGH", "CRITICAL"] as const).map((l) => (
        <div className="lg-row" key={l}>
          <span className="sw" style={{ background: RISK_COLOR[l] }} />
          <span>{l}</span>
        </div>
      ))}
      <div className="tiny muted" style={{ marginTop: 6, borderTop: "1px solid var(--line)", paddingTop: 5 }}>
        {tileLabel ?? "OpenStreetMap tile layer"}
      </div>
    </div>
  );
}
