import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import type {
  GISLayerId,
  HistoricalIncident,
  Infrastructure,
  RiskLevel,
  RiskZone,
  RoadStatus,
  Sensor,
  Village,
} from "@/types";
import type { LiveGeoFeature, MapSelection } from "./RiskMap";

interface Props {
  zones: RiskZone[];
  sensors?: Sensor[];
  roads?: RoadStatus[];
  villages?: Village[];
  infrastructure?: Infrastructure[];
  incidents?: HistoricalIncident[];
  seismicFeatures?: LiveGeoFeature[];
  soilFeatures?: LiveGeoFeature[];
  gsiFeatures?: LiveGeoFeature[];
  osmFeatures?: LiveGeoFeature[];
  activeLayers: Set<GISLayerId>;
  selected?: MapSelection | null;
  onSelect?: (sel: MapSelection) => void;
  height?: number;
  showStateLabels?: boolean;
}

type BasemapType = "osm" | "topo" | "satellite";

const BASEMAP_URLS: Record<BasemapType, { url: string; attribution: string; maxZoom: number }> = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  },
  topo: {
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution: 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
    maxZoom: 17,
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
    maxZoom: 18,
  },
};

const ROAD_COLORS: Record<RoadStatus["status"], string> = {
  OPEN: "#16a34a",
  AT_RISK: "#ea580c",
  RESTRICTED: "#dc2626",
  BLOCKED: "#991b1b",
};

const RISK_COLORS: Record<RiskLevel, string> = {
  CRITICAL: "#dc2626",
  HIGH: "#ea580c",
  MODERATE: "#d97706",
  LOW: "#16a34a",
};

export function Leaflet2DMap({
  zones,
  sensors = [],
  roads = [],
  villages = [],
  infrastructure = [],
  incidents = [],
  seismicFeatures = [],
  soilFeatures = [],
  gsiFeatures = [],
  osmFeatures = [],
  activeLayers,
  selected,
  onSelect,
  height = 540,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const tileLayerRef = useRef<L.TileLayer | null>(null);
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const [basemap, setBasemap] = useState<BasemapType>("topo");

  // Center around Kohima / Dzüdza Gorge Corridor
  const defaultCenter: [number, number] = [25.6751, 94.1086];
  const defaultZoom = 11;

  // Initialize Leaflet Map instance
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: defaultCenter,
      zoom: defaultZoom,
      zoomControl: true,
    });

    const cfg = BASEMAP_URLS[basemap];
    const tileLayer = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: cfg.maxZoom,
    }).addTo(map);

    const layerGroup = L.layerGroup().addTo(map);

    tileLayerRef.current = tileLayer;
    layerGroupRef.current = layerGroup;
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update Basemap Tiles
  useEffect(() => {
    if (!mapRef.current) return;
    if (tileLayerRef.current) {
      tileLayerRef.current.remove();
    }
    const cfg = BASEMAP_URLS[basemap];
    const newTileLayer = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: cfg.maxZoom,
    }).addTo(mapRef.current);
    tileLayerRef.current = newTileLayer;
    newTileLayer.bringToBack();
  }, [basemap]);

  // Auto-fit bounds when scope/zones change
  useEffect(() => {
    if (!mapRef.current || !zones || zones.length === 0) return;
    const coords = zones
      .filter((z) => z.center && typeof z.center.lat === "number" && typeof z.center.lng === "number")
      .map((z) => [z.center.lat, z.center.lng] as [number, number]);
    if (coords.length > 0) {
      const bounds = L.latLngBounds(coords);
      if (bounds.isValid()) {
        mapRef.current.fitBounds(bounds.pad(0.15), { maxZoom: 13 });
      }
    }
  }, [zones]);

  // Invalidate map size on container render/resize to ensure tiles never misalign
  useEffect(() => {
    if (!mapRef.current) return;
    const timer = setTimeout(() => {
      mapRef.current?.invalidateSize();
    }, 150);
    const handleResize = () => {
      mapRef.current?.invalidateSize();
    };
    window.addEventListener("resize", handleResize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", handleResize);
    };
  }, [height]);

  // Render Operational Layers
  useEffect(() => {
    const lg = layerGroupRef.current;
    if (!lg || !mapRef.current) return;
    lg.clearLayers();

    // 1. GSI Bhukosh NLSM Susceptibility Polygons & Historical Landslides
    if (activeLayers.has("gsi_susceptibility")) {
      gsiFeatures.forEach((feat) => {
        const props = feat.properties;
        const geom = feat.geometry;

        if (geom.type === "Polygon" && geom.coordinates?.[0]) {
          // Convert [lng, lat] to [lat, lng] for Leaflet
          const latLngs = (geom.coordinates[0] as number[][]).map(([lng, lat]) => [lat, lng] as [number, number]);
          const color = String(props.color ?? "#e53e3e");
          const poly = L.polygon(latLngs, {
            color: color,
            fillColor: color,
            fillOpacity: 0.28,
            weight: 2,
            dashArray: "4, 4",
          });
          poly.bindTooltip(`<b>GSI NLSM:</b> ${props.zone_name}<br/><b>Susceptibility:</b> ${props.susceptibility_class}<br/><b>Lithology:</b> ${props.geology ?? "Colluvium"}`);
          poly.on("click", () => onSelect?.({ kind: "gsi_zone", id: String(props.id) }));
          lg.addLayer(poly);
        } else if (geom.type === "Point" && geom.coordinates) {
          const [lng, lat] = geom.coordinates as number[];
          const marker = L.circleMarker([lat, lng], {
            radius: 8,
            fillColor: "#e53e3e",
            color: "#ffffff",
            weight: 2,
            fillOpacity: 0.9,
          });
          marker.bindTooltip(`<b>GSI Historical Slide:</b> ${props.name}<br/><b>Date:</b> ${props.date}<br/><b>Impact:</b> ${props.impact ?? "Highway cut off"}`);
          marker.on("click", () => onSelect?.({ kind: "gsi_zone", id: String(props.id) }));
          lg.addLayer(marker);
        }
      });
    }

    // 2. Risk Zones Polygons & Heatmap
    if (activeLayers.has("risk_heatmap")) {
      zones.forEach((z) => {
        const color = RISK_COLORS[z.riskLevel] ?? "#ea580c";
        if (z.geometry?.coordinates?.[0]) {
          const latLngs = z.geometry.coordinates[0].map(([lng, lat]) => [lat, lng] as [number, number]);
          const poly = L.polygon(latLngs, {
            color: color,
            fillColor: color,
            fillOpacity: 0.22,
            weight: selected?.id === z.id ? 3 : 1.5,
          });
          poly.bindTooltip(`<b>Zone:</b> ${z.name}<br/><b>Risk:</b> ${z.riskLevel} (${z.riskScore}/100)<br/><b>Rainfall:</b> ${z.rainfall24h} mm`);
          poly.on("click", () => onSelect?.({ kind: "zone", id: z.id }));
          lg.addLayer(poly);
        } else if (z.center) {
          const circle = L.circleMarker([z.center.lat, z.center.lng], {
            radius: 12,
            fillColor: color,
            color: "#ffffff",
            weight: 1.5,
            fillOpacity: 0.6,
          });
          circle.bindTooltip(`<b>Zone:</b> ${z.name}<br/><b>Risk:</b> ${z.riskLevel} (${z.riskScore}/100)`);
          circle.on("click", () => onSelect?.({ kind: "zone", id: z.id }));
          lg.addLayer(circle);
        }
      });
    }

    // 3. Roads & Highways (NH-29)
    if (activeLayers.has("roads")) {
      roads.forEach((r) => {
        if (!r.path || r.path.length < 2) return;
        const latLngs = r.path.map(([lng, lat]) => [lat, lng] as [number, number]);
        const color = ROAD_COLORS[r.status] ?? "#5b6f6a";
        const line = L.polyline(latLngs, {
          color: color,
          weight: selected?.id === r.id ? 5 : 3.5,
          opacity: 0.9,
          dashArray: r.status === "BLOCKED" ? "6, 6" : undefined,
        });
        line.bindTooltip(`<b>Road:</b> ${r.name}<br/><b>Status:</b> ${r.status}<br/><b>Risk:</b> ${r.riskLevel}`);
        line.on("click", () => onSelect?.({ kind: "road", id: r.id }));
        lg.addLayer(line);
      });
    }

    // 4. Live Seismic Triggers (NCS India / USGS)
    if (activeLayers.has("seismic")) {
      seismicFeatures.forEach((feat) => {
        const props = feat.properties;
        const coords = feat.geometry.coordinates as number[];
        const [lng, lat, depth] = coords;
        const mag = Number(props.magnitude ?? 3.0);
        const pot = String(props.trigger_potential ?? "LOW");
        const color = pot === "CRITICAL" ? "#e53e3e" : pot === "HIGH" ? "#dd6b20" : pot === "MODERATE" ? "#d69e2e" : "#38a169";

        // Epicenter Pulse Ring
        const ring = L.circle([lat, lng], {
          radius: Math.min(25000, mag * 4000),
          fillColor: color,
          color: color,
          weight: 1.5,
          dashArray: "4, 4",
          fillOpacity: 0.08,
        });
        lg.addLayer(ring);

        // Epicenter Marker
        const marker = L.circleMarker([lat, lng], {
          radius: Math.max(6, mag * 2.5),
          fillColor: color,
          color: "#ffffff",
          weight: 2,
          fillOpacity: 0.9,
        });
        marker.bindTooltip(`<b>Seismic Trigger:</b> ${props.title}<br/><b>Magnitude:</b> M${mag.toFixed(1)}<br/><b>Focal Depth:</b> ${depth ?? props.depth_km} km<br/><b>Landslide Potential:</b> ${pot}<br/><b>Source:</b> ${props.source}`);
        marker.on("click", () => onSelect?.({ kind: "seismic", id: String(props.id) }));
        lg.addLayer(marker);
      });
    }

    // 5. Live Soil Moisture & Weather Stations (Open-Meteo & IMD AWS)
    if (activeLayers.has("soil_moisture")) {
      soilFeatures.forEach((feat) => {
        const props = feat.properties;
        const coords = feat.geometry.coordinates as number[];
        const [lng, lat, elev] = coords;
        const status = String(props.slope_stability_status ?? "LOW");
        const color = status === "CRITICAL" ? "#e53e3e" : status === "HIGH" ? "#dd6b20" : status === "MODERATE" ? "#d69e2e" : "#38a169";

        const marker = L.circleMarker([lat, lng], {
          radius: 8,
          fillColor: color,
          color: "#ffffff",
          weight: 2,
          fillOpacity: 0.95,
        });
        marker.bindTooltip(
          `<b>AWS Station:</b> ${props.name} (${elev ?? props.elevation_m}m)<br/>` +
          `<b>Root Saturation:</b> ${(Number(props.saturation_ratio_m ?? 0) * 100).toFixed(1)}%<br/>` +
          `<b>Factor of Safety (FS):</b> ${props.factor_of_safety_fs}<br/>` +
          `<b>24h Rainfall:</b> ${props.rainfall_24h_mm} mm<br/>` +
          `<b>Status:</b> ${status}`
        );
        marker.on("click", () => onSelect?.({ kind: "soil_station", id: String(props.id) }));
        lg.addLayer(marker);
      });
    }

    // 6. Live Lifelines & Infrastructure (OpenStreetMap)
    if (activeLayers.has("osm_infrastructure")) {
      osmFeatures.forEach((feat) => {
        const props = feat.properties;
        const coords = feat.geometry.coordinates as number[];
        const [lng, lat] = coords;
        const isHosp = String(props.type).includes("HOSPITAL");
        const color = isHosp ? "#3182ce" : "#805ad5";

        const marker = L.circleMarker([lat, lng], {
          radius: 7,
          fillColor: color,
          color: "#ffffff",
          weight: 2,
          fillOpacity: 0.9,
        });
        marker.bindTooltip(`<b>OSM Lifeline:</b> ${props.name}<br/><b>Type:</b> ${props.type}<br/><b>Address:</b> ${props.address}`);
        marker.on("click", () => onSelect?.({ kind: "osm_asset", id: String(props.id) }));
        lg.addLayer(marker);
      });
    }

    // 7. Sensors
    if (activeLayers.has("sensors")) {
      sensors.forEach((s) => {
        const color = s.status === "ONLINE" ? "#38a169" : s.status === "DEGRADED" ? "#dd6b20" : "#e53e3e";
        const marker = L.circleMarker([s.location.lat, s.location.lng], {
          radius: 5.5,
          fillColor: color,
          color: "#ffffff",
          weight: 1.5,
          fillOpacity: 0.9,
        });
        marker.bindTooltip(`<b>Sensor:</b> ${s.id} (${s.type})<br/><b>Status:</b> ${s.status}<br/><b>Reading:</b> ${s.reading} ${s.unit}`);
        marker.on("click", () => onSelect?.({ kind: "sensor", id: s.id }));
        lg.addLayer(marker);
      });
    }

    // 8. Settlements / Villages
    if (activeLayers.has("settlements")) {
      villages.forEach((v) => {
        const marker = L.circleMarker([v.location.lat, v.location.lng], {
          radius: 5,
          fillColor: "#ffffff",
          color: RISK_COLORS[v.riskLevel] ?? "#ea580c",
          weight: 2,
          fillOpacity: 0.8,
        });
        marker.bindTooltip(`<b>Village:</b> ${v.name}<br/><b>Population:</b> ${v.population}<br/><b>Risk:</b> ${v.riskLevel}`);
        marker.on("click", () => onSelect?.({ kind: "village", id: v.id }));
        lg.addLayer(marker);
      });
    }

    // 9. Historical Incidents
    if (activeLayers.has("incidents")) {
      incidents.forEach((inc) => {
        const marker = L.circleMarker([inc.center.lat, inc.center.lng], {
          radius: 6,
          fillColor: "#e53e3e",
          color: "#ffffff",
          weight: 1.5,
          fillOpacity: 0.9,
        });
        marker.bindTooltip(`<b>Recorded Slide:</b> ${inc.incidentType}<br/><b>Location:</b> ${inc.location}<br/><b>Severity:</b> ${inc.severity}`);
        marker.on("click", () => onSelect?.({ kind: "incident", id: inc.id }));
        lg.addLayer(marker);
      });
    }
  }, [
    zones,
    sensors,
    roads,
    villages,
    infrastructure,
    incidents,
    seismicFeatures,
    soilFeatures,
    gsiFeatures,
    osmFeatures,
    activeLayers,
    selected,
    onSelect,
  ]);

  return (
    <div style={{ position: "relative", width: "100%", height, borderRadius: 8, overflow: "hidden" }}>
      {/* Basemap Switcher Toolbar */}
      <div
        style={{
          position: "absolute",
          top: 10,
          right: 10,
          zIndex: 1000,
          background: "rgba(13, 20, 36, 0.92)",
          backdropFilter: "blur(8px)",
          padding: "3px 6px",
          borderRadius: 6,
          border: "1px solid rgba(255, 255, 255, 0.18)",
          display: "flex",
          gap: 4,
          alignItems: "center",
          boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
        }}
      >
        <span style={{ fontSize: 10, color: "#94a3b8", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, padding: "0 4px" }}>
          Basemap:
        </span>
        {(
          [
            { key: "topo", label: "🏔️ Topo", title: "OpenTopoMap (Contour lines & hill relief)" },
            { key: "satellite", label: "🛰️ Satellite", title: "Esri World Imagery (Aerial photo)" },
            { key: "osm", label: "🗺️ Street", title: "OpenStreetMap (Roads & places)" },
          ] as const
        ).map((b) => (
          <button
            key={b.key}
            type="button"
            title={b.title}
            onClick={() => setBasemap(b.key)}
            style={{
              padding: "4px 8px",
              fontSize: 11,
              fontWeight: 600,
              borderRadius: 4,
              border: basemap === b.key ? "1px solid #38bdf8" : "1px solid transparent",
              background: basemap === b.key ? "rgba(56, 189, 248, 0.25)" : "transparent",
              color: basemap === b.key ? "#38bdf8" : "#cbd5e1",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            {b.label}
          </button>
        ))}
      </div>

      {/* Actual Leaflet Map Container */}
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
