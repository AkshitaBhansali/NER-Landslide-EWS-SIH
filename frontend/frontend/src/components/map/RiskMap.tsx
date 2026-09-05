import { useEffect, useId, useMemo, useRef, useState } from "react";
import type {
  GISLayerId,
  HistoricalIncident,
  Infrastructure,
  RiskZone,
  RoadStatus,
  Sensor,
  Village,
} from "@/types";
import { riskVar } from "@/utils";
import { FULL_VIEW, VIEW_H, VIEW_W, polygonPoints, project, projectCoord } from "./projection";
import { STATES } from "@/data/regions";

/**
 * Schematic operational map.
 *
 * The prototype renders its own SVG rather than pulling a tile provider, so the dashboard
 * works with no network — the actual deployment condition in much of the NER. Every layer
 * already consumes GeoJSON-ordered coordinates, so replacing this renderer with MapLibre
 * (2D) or Cesium (3D terrain) is a swap of this component plus `projection.ts`, with no
 * change to the data flowing in.
 */

export interface MapSelection {
  kind: "zone" | "sensor" | "road" | "incident" | "village" | "infrastructure";
  id: string;
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
  height?: number;
  showStateLabels?: boolean;
}

const ROAD_COLOR: Record<RoadStatus["status"], string> = {
  OPEN: "#5b6f6a",
  AT_RISK: "var(--mod)",
  RESTRICTED: "var(--high)",
  BLOCKED: "var(--sev)",
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
  height = 460,
  showStateLabels = true,
}: Props) {
  const gid = useId().replace(/:/g, "");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);

  // Reset the viewport when the scope changes, otherwise the user is left panned
  // to a district that is no longer on screen.
  const scopeKey = zones.map((z) => z.id).join(",").slice(0, 60);
  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [scopeKey]);

  const clampPan = (p: { x: number; y: number }, z: number) => {
    const limitX = (VIEW_W * (z - 1)) / 2 / z;
    const limitY = (VIEW_H * (z - 1)) / 2 / z;
    return {
      x: Math.max(-limitX, Math.min(limitX, p.x)),
      y: Math.max(-limitY, Math.min(limitY, p.y)),
    };
  };

  const setZoomClamped = (next: number) => {
    const z = Math.max(1, Math.min(6, next));
    setZoom(z);
    setPan((p) => clampPan(p, z));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (zoom === 1) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current || !frameRef.current) return;
    const rect = frameRef.current.getBoundingClientRect();
    const scale = VIEW_W / rect.width / zoom;
    setPan(
      clampPan(
        {
          x: drag.current.px + (e.clientX - drag.current.x) * scale,
          y: drag.current.py + (e.clientY - drag.current.y) * scale,
        },
        zoom,
      ),
    );
  };
  const endDrag = () => {
    drag.current = null;
  };

  const transform = `translate(${VIEW_W / 2} ${VIEW_H / 2}) scale(${zoom}) translate(${-VIEW_W / 2 + pan.x} ${-VIEW_H / 2 + pan.y})`;

  const graticule = useMemo(() => {
    const lines: { x1: number; y1: number; x2: number; y2: number }[] = [];
    for (let lng = Math.ceil(FULL_VIEW.minLng); lng <= FULL_VIEW.maxLng; lng += 2) {
      const a = project({ lat: FULL_VIEW.minLat, lng });
      const b = project({ lat: FULL_VIEW.maxLat, lng });
      lines.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }
    for (let lat = Math.ceil(FULL_VIEW.minLat); lat <= FULL_VIEW.maxLat; lat += 2) {
      const a = project({ lat, lng: FULL_VIEW.minLng });
      const b = project({ lat, lng: FULL_VIEW.maxLng });
      lines.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }
    return lines;
  }, []);

  const isSel = (kind: MapSelection["kind"], id: string) =>
    selected?.kind === kind && selected?.id === id;

  return (
    <div
      className="map-frame"
      ref={frameRef}
      style={{ height }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
    >
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid slice"
        style={{ height: "100%", cursor: zoom > 1 ? "grab" : "default" }}
        role="group"
        aria-label="Landslide risk map of the North Eastern Region"
      >
        <defs>
          <radialGradient id={`heat-${gid}`}>
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.55" />
            <stop offset="70%" stopColor="currentColor" stopOpacity="0.16" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </radialGradient>
          <pattern id={`terrain-${gid}`} width="26" height="26" patternUnits="userSpaceOnUse">
            <path d="M0 26 L13 6 L26 26" fill="none" stroke="#c8d2c6" strokeWidth="0.9" />
          </pattern>
        </defs>

        {/* base */}
        <rect x={0} y={0} width={VIEW_W} height={VIEW_H} fill="#eef1ea" />
        <g transform={transform}>
          {/* A faint relief hatch is drawn always, as cartographic context rather than
              as a toggleable data layer. It carries no values and answers no question
              on its own, which is exactly why it is not in the layer picker. */}
          <rect x={0} y={0} width={VIEW_W} height={VIEW_H} fill={`url(#terrain-${gid})`} opacity={0.35} />

          {graticule.map((l, i) => (
            <line key={i} {...l} stroke="#dfe4dc" strokeWidth={0.8} />
          ))}

          {/* rainfall wash */}
          {activeLayers.has("rainfall") &&
            zones.map((z) => {
              const p = project(z.center);
              const r = 26 + (z.rainfall24h / 200) * 60;
              return (
                <circle
                  key={`rain-${z.id}`}
                  cx={p.x}
                  cy={p.y}
                  r={r}
                  fill="#2f6f9e"
                  opacity={Math.min(0.28, 0.06 + z.rainfall24h / 700)}
                />
              );
            })}

          {/* risk heatmap */}
          {activeLayers.has("risk_heatmap") &&
            zones.map((z) => {
              const p = project(z.center);
              const color = riskVar(z.riskLevel);
              const r = 20 + (z.riskScore / 100) * 52;
              return (
                <g key={`heat-${z.id}`} style={{ color }}>
                  <circle cx={p.x} cy={p.y} r={r} fill={`url(#heat-${gid})`} />
                  {z.geometry && (
                    <polygon
                      points={polygonPoints(z.geometry.coordinates[0])}
                      fill={color}
                      fillOpacity={0.16}
                      stroke={color}
                      strokeWidth={isSel("zone", z.id) ? 2.6 : 1.2}
                      strokeDasharray={z.riskLevel === "CRITICAL" ? undefined : "3 2"}
                    />
                  )}
                </g>
              );
            })}

          {/* roads */}
          {activeLayers.has("roads") &&
            roads.map((r) => (
              <g key={r.id}>
                <path
                  d={r.path
                    .map((c, i) => {
                      const p = projectCoord(c);
                      return `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
                    })
                    .join(" ")}
                  fill="none"
                  stroke={ROAD_COLOR[r.status]}
                  strokeWidth={isSel("road", r.id) ? 4 : r.status === "BLOCKED" ? 3 : 2.2}
                  strokeLinecap="round"
                  strokeDasharray={r.status === "BLOCKED" ? "7 4" : undefined}
                  style={{ cursor: onSelect ? "pointer" : undefined }}
                  onClick={() => onSelect?.({ kind: "road", id: r.id })}
                >
                  <title>{`${r.name} — ${r.status}`}</title>
                </path>
              </g>
            ))}

          {/* villages */}
          {activeLayers.has("settlements") &&
            villages.map((v) => {
              const p = project(v.location);
              return (
                <g
                  key={v.id}
                  className="zone-marker"
                  onClick={() => onSelect?.({ kind: "village", id: v.id })}
                >
                  <rect
                    x={p.x - 3}
                    y={p.y - 3}
                    width={6}
                    height={6}
                    fill="#fff"
                    stroke={riskVar(v.riskLevel)}
                    strokeWidth={1.6}
                  >
                    <title>{`${v.name} — ${v.riskLevel} · ${v.connectivity}`}</title>
                  </rect>
                </g>
              );
            })}

          {/* infrastructure */}
          {activeLayers.has("infrastructure") &&
            infrastructure.map((inf) => {
              const p = project(inf.location);
              return (
                <g
                  key={inf.id}
                  className="zone-marker"
                  onClick={() => onSelect?.({ kind: "infrastructure", id: inf.id })}
                >
                  <path
                    d={`M${p.x},${p.y - 5} L${p.x + 4.5},${p.y + 3.5} L${p.x - 4.5},${p.y + 3.5} Z`}
                    fill="#fff"
                    stroke={riskVar(inf.exposure)}
                    strokeWidth={1.5}
                  >
                    <title>{`${inf.name} — exposure ${inf.exposure}`}</title>
                  </path>
                </g>
              );
            })}

          {/* incidents */}
          {activeLayers.has("incidents") &&
            incidents.map((inc) => {
              const p = project(inc.center);
              return (
                <g
                  key={inc.id}
                  className="zone-marker"
                  onClick={() => onSelect?.({ kind: "incident", id: inc.id })}
                >
                  <path
                    d={`M${p.x - 4},${p.y - 4} L${p.x + 4},${p.y + 4} M${p.x + 4},${p.y - 4} L${p.x - 4},${p.y + 4}`}
                    stroke={riskVar(inc.severity)}
                    strokeWidth={1.8}
                    strokeLinecap="round"
                  >
                    <title>{`${inc.incidentType} — ${inc.location}`}</title>
                  </path>
                </g>
              );
            })}

          {/* sensors */}
          {activeLayers.has("sensors") &&
            sensors.map((s) => {
              const p = project(s.location);
              const color =
                s.status === "ONLINE" ? "var(--low)" : s.status === "DEGRADED" ? "var(--mod)" : "var(--sev)";
              return (
                <g
                  key={s.id}
                  className="zone-marker"
                  tabIndex={0}
                  role="button"
                  aria-label={`Sensor ${s.id}, ${s.status}`}
                  onClick={() => onSelect?.({ kind: "sensor", id: s.id })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") onSelect?.({ kind: "sensor", id: s.id });
                  }}
                >
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={isSel("sensor", s.id) ? 5 : 3.2}
                    fill={color}
                    stroke="#fff"
                    strokeWidth={1.2}
                  >
                    <title>{`${s.id} — ${s.name} (${s.status})`}</title>
                  </circle>
                  {s.status === "OFFLINE" && (
                    <circle cx={p.x} cy={p.y} r={6.5} fill="none" stroke="var(--sev)" strokeWidth={0.9} strokeDasharray="2 2" />
                  )}
                </g>
              );
            })}

          {/* zone centroids — always on, they are the primary answer to "where?" */}
          {zones.map((z) => {
            const p = project(z.center);
            const color = riskVar(z.riskLevel);
            const critical = z.riskLevel === "CRITICAL";
            return (
              <g
                key={z.id}
                className="zone-marker"
                tabIndex={0}
                role="button"
                aria-label={`${z.name}, risk ${z.riskLevel}, score ${z.riskScore}`}
                onClick={() => onSelect?.({ kind: "zone", id: z.id })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") onSelect?.({ kind: "zone", id: z.id });
                }}
              >
                {critical && (
                  <circle cx={p.x} cy={p.y} r={12} fill="none" stroke={color} strokeWidth={1.2} opacity={0.65}>
                    <animate attributeName="r" values="8;16;8" dur="2.4s" repeatCount="indefinite" />
                    <animate attributeName="opacity" values="0.7;0;0.7" dur="2.4s" repeatCount="indefinite" />
                  </circle>
                )}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={isSel("zone", z.id) ? 8.5 : 6.5}
                  fill={color}
                  stroke="#fff"
                  strokeWidth={1.8}
                />
                <text
                  x={p.x}
                  y={p.y + 2.8}
                  textAnchor="middle"
                  fontSize={7}
                  fill="#fff"
                  fontWeight={700}
                  style={{ pointerEvents: "none", fontFamily: "var(--font-mono)" }}
                >
                  {z.riskScore}
                </text>
                <title>{`${z.name} — ${z.riskLevel} (${z.riskScore})`}</title>
              </g>
            );
          })}

          {showStateLabels &&
            zoom < 2.2 &&
            STATES.map((s) => {
              const p = project(s.center);
              return (
                <text
                  key={s.code}
                  x={p.x}
                  y={p.y - 26}
                  textAnchor="middle"
                  fontSize={9.5}
                  fill="#7c8a85"
                  style={{ pointerEvents: "none", letterSpacing: "0.06em", textTransform: "uppercase" }}
                >
                  {s.name}
                </text>
              );
            })}
        </g>
      </svg>

      <div className="map-controls noprint">
        <button type="button" onClick={() => setZoomClamped(zoom + 0.6)} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={() => setZoomClamped(zoom - 0.6)} aria-label="Zoom out">
          −
        </button>
        <button
          type="button"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
          aria-label="Reset view"
          title="Reset view"
          style={{ fontSize: 11 }}
        >
          ⌂
        </button>
      </div>

      <MapLegend />
    </div>
  );
}

export function MapLegend() {
  return (
    <div className="map-legend">
      <div className="eyebrow" style={{ marginBottom: 3 }}>
        Risk level
      </div>
      {(["LOW", "MODERATE", "HIGH", "CRITICAL"] as const).map((l) => (
        <div className="lg-row" key={l}>
          <span className="sw" style={{ background: riskVar(l) }} />
          <span>{l}</span>
        </div>
      ))}
      <div className="tiny muted" style={{ marginTop: 6, borderTop: "1px solid var(--line)", paddingTop: 5 }}>
        Schematic base map · synthetic positions
      </div>
    </div>
  );
}
