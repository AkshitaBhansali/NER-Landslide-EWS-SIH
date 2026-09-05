import { useMemo, useState } from "react";
import type { RiskLevel, TerrainProfile } from "@/types";
import { riskVar } from "@/utils";

/**
 * Isometric DEM preview.
 *
 * A real 3D terrain view belongs in Cesium or MapLibre with terrain tiles; that is
 * This renders the same `demGrid` a raster would produce, so the
 * data contract (`TerrainProfile.demGrid`, elevation range, risk overlay) is already
 * exercised and the swap is a renderer change, not a data change.
 */
export function Terrain3D({
  profile,
  riskLevel,
  height = 300,
}: {
  profile: TerrainProfile;
  riskLevel: RiskLevel;
  height?: number;
}) {
  const [exaggeration, setExaggeration] = useState(1);
  const [rotated, setRotated] = useState(false);

  const grid = profile.demGrid;
  const rows = grid.length;
  const cols = grid[0]?.length ?? 0;

  const cells = useMemo(() => {
    const W = 620;
    const cellW = W / (rows + cols);
    const cellH = cellW * 0.52;
    const originX = W / 2;
    const originY = 62;
    const relief = 105 * exaggeration;

    const out: { d: string; fill: string; key: string; z: number; elev: number }[] = [];

    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const rr = rotated ? cols - 1 - c : r;
        const cc = rotated ? r : c;
        const h = grid[r][c];
        const x = originX + (cc - rr) * cellW;
        const y = originY + (cc + rr) * cellH - h * relief;

        const top = `M${x},${y} L${x + cellW},${y + cellH} L${x},${y + cellH * 2} L${x - cellW},${y + cellH} Z`;
        // Shade by elevation, then tint the highest ground with the zone's risk colour.
        const light = 0.42 + h * 0.5;
        const base = `rgb(${Math.round(120 * light + 60)}, ${Math.round(140 * light + 55)}, ${Math.round(118 * light + 52)})`;
        out.push({ d: top, fill: base, key: `t-${r}-${c}`, z: cc + rr, elev: h });

        const side = `M${x - cellW},${y + cellH} L${x},${y + cellH * 2} L${x},${y + cellH * 2 + 16} L${x - cellW},${y + cellH + 16} Z`;
        out.push({
          d: side,
          fill: `rgb(${Math.round(96 * light + 40)}, ${Math.round(112 * light + 38)}, ${Math.round(94 * light + 36)})`,
          key: `s-${r}-${c}`,
          z: cc + rr,
          elev: h,
        });
      }
    }
    return out.sort((a, b) => a.z - b.z);
  }, [grid, rows, cols, exaggeration, rotated]);

  const peak = cells.filter((c) => c.elev > 0.78 && c.key.startsWith("t")).slice(0, 14);

  return (
    <div>
      <div className="row between" style={{ marginBottom: 8 }}>
        <span className="tiny muted">
          Vertical exaggeration ×{exaggeration.toFixed(1)} · elevation {profile.elevationMin}–
          {profile.elevationMax} m
        </span>
        <div className="row" style={{ gap: 6 }}>
          <label className="tiny muted row" style={{ gap: 6 }}>
            Relief
            <input
              type="range"
              min={0.4}
              max={1.8}
              step={0.1}
              value={exaggeration}
              onChange={(e) => setExaggeration(Number(e.target.value))}
              aria-label="Vertical exaggeration"
              style={{ width: 90, minHeight: 0 }}
            />
          </label>
          <button className="btn sm" type="button" onClick={() => setRotated((r) => !r)}>
            Rotate 90°
          </button>
        </div>
      </div>

      <div
        style={{
          background: "linear-gradient(180deg, #eef2ec 0%, #e4e9e1 100%)",
          borderRadius: "var(--r-sm)",
          border: "1px solid var(--line)",
          overflow: "hidden",
          height,
        }}
      >
        <svg
          viewBox="0 0 620 360"
          style={{ width: "100%", height: "100%" }}
          role="img"
          aria-label={`Isometric terrain model, mean slope ${profile.slopeMean} degrees`}
        >
          {cells.map((c) => (
            <path key={c.key} d={c.d} fill={c.fill} stroke="rgba(0,0,0,0.05)" strokeWidth={0.3} />
          ))}
          {peak.map((c) => (
            <path key={`risk-${c.key}`} d={c.d} fill={riskVar(riskLevel)} opacity={0.34} />
          ))}
        </svg>
      </div>

      <div className="chart-legend" style={{ marginTop: 6 }}>
        <span>
          <i style={{ background: "#7b8f7c", width: 10, height: 10, borderRadius: 2 }} />
          Terrain surface (DEM)
        </span>
        <span>
          <i style={{ background: riskVar(riskLevel), width: 10, height: 10, borderRadius: 2 }} />
          Modelled risk on upper slopes
        </span>
      </div>
      <div className="tiny muted" style={{ marginTop: 4 }}>
        Synthetic DEM placeholder — the deployment reads CartoDEM 30 m tiles through the GIS service.
      </div>
    </div>
  );
}
