import { useId, useState, type ReactNode } from "react";
import type { RiskLevel } from "@/types";
import { riskVar } from "@/utils";

/**
 * Charts are hand-rolled SVG rather than a charting library: the bundle stays small and
 * fully offline-capable (which matters for the low-connectivity deployment target), and
 * every element can carry the ARIA description an emergency dashboard needs.
 */

const AXIS = "var(--line-2)";
const GRID = "var(--line)";
const LABEL = "var(--ink-3)";

interface Frame {
  w: number;
  h: number;
  pad: { t: number; r: number; b: number; l: number };
}

const defaultFrame: Frame = { w: 640, h: 220, pad: { t: 12, r: 12, b: 26, l: 34 } };

function ChartFrame({
  frame = defaultFrame,
  title,
  children,
  legend,
  height,
}: {
  frame?: Frame;
  title: string;
  children: ReactNode;
  legend?: { label: string; color: string }[];
  height?: number;
}) {
  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${frame.w} ${frame.h}`}
        role="img"
        aria-label={title}
        style={{ height: height ?? undefined }}
        preserveAspectRatio="xMidYMid meet"
      >
        {children}
      </svg>
      {legend && (
        <div className="chart-legend">
          {legend.map((l) => (
            <span key={l.label}>
              <i style={{ background: l.color }} />
              {l.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const niceMax = (max: number) => {
  if (max <= 0) return 10;
  const mag = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / mag) * mag;
};

/* ------------------------------------------------------------------ line / area */

export interface Series {
  label: string;
  color: string;
  values: number[];
  fill?: boolean;
  dashed?: boolean;
}

export function LineChart({
  series,
  labels,
  title,
  yMax,
  yLabel,
  height,
  threshold,
}: {
  series: Series[];
  labels: string[];
  title: string;
  yMax?: number;
  yLabel?: string;
  height?: number;
  threshold?: { value: number; label: string; color?: string };
}) {
  const f = defaultFrame;
  const gid = useId().replace(/:/g, "");
  const [hover, setHover] = useState<number | null>(null);

  const allValues = series.flatMap((s) => s.values);
  const max = yMax ?? niceMax(Math.max(...allValues, threshold?.value ?? 0, 1));
  const n = Math.max(labels.length, 1);
  const innerW = f.w - f.pad.l - f.pad.r;
  const innerH = f.h - f.pad.t - f.pad.b;

  const x = (i: number) => f.pad.l + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const y = (v: number) => f.pad.t + innerH - (v / max) * innerH;

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(max * t));
  const labelStep = Math.max(1, Math.ceil(n / 6));

  return (
    <ChartFrame
      title={title}
      height={height}
      legend={series.map((s) => ({ label: s.label, color: s.color }))}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={f.pad.l} x2={f.w - f.pad.r} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
          <text x={f.pad.l - 6} y={y(t) + 3.5} textAnchor="end" fontSize={9} fill={LABEL} className="mono">
            {t}
          </text>
        </g>
      ))}

      {threshold && (
        <g>
          <line
            x1={f.pad.l}
            x2={f.w - f.pad.r}
            y1={y(threshold.value)}
            y2={y(threshold.value)}
            stroke={threshold.color ?? "var(--sev)"}
            strokeWidth={1.2}
            strokeDasharray="5 4"
          />
          <text
            x={f.w - f.pad.r}
            y={y(threshold.value) - 4}
            textAnchor="end"
            fontSize={9}
            fill={threshold.color ?? "var(--sev)"}
          >
            {threshold.label}
          </text>
        </g>
      )}

      {series.map((s, si) => {
        const pts = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
        return (
          <g key={s.label}>
            {s.fill && (
              <>
                <defs>
                  <linearGradient id={`g-${gid}-${si}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={s.color} stopOpacity="0.28" />
                    <stop offset="100%" stopColor={s.color} stopOpacity="0.02" />
                  </linearGradient>
                </defs>
                <polygon
                  points={`${f.pad.l},${y(0)} ${pts} ${x(s.values.length - 1)},${y(0)}`}
                  fill={`url(#g-${gid}-${si})`}
                />
              </>
            )}
            <polyline
              points={pts}
              fill="none"
              stroke={s.color}
              strokeWidth={1.8}
              strokeDasharray={s.dashed ? "4 3" : undefined}
              strokeLinejoin="round"
            />
          </g>
        );
      })}

      {hover !== null && (
        <g>
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={f.pad.t}
            y2={f.pad.t + innerH}
            stroke="var(--ink-4)"
            strokeWidth={1}
          />
          {series.map((s) => (
            <circle key={s.label} cx={x(hover)} cy={y(s.values[hover] ?? 0)} r={3} fill={s.color} />
          ))}
          <text
            x={Math.min(x(hover) + 6, f.w - f.pad.r - 90)}
            y={f.pad.t + 10}
            fontSize={9.5}
            fill="var(--ink)"
            className="mono"
          >
            {labels[hover]} · {series.map((s) => `${s.label} ${s.values[hover]}`).join("  ")}
          </text>
        </g>
      )}

      {labels.map((l, i) =>
        i % labelStep === 0 ? (
          <text key={`${l}-${i}`} x={x(i)} y={f.h - 8} textAnchor="middle" fontSize={9} fill={LABEL}>
            {l}
          </text>
        ) : null,
      )}

      {yLabel && (
        <text x={2} y={10} fontSize={9} fill={LABEL}>
          {yLabel}
        </text>
      )}

      {labels.map((_, i) => (
        <rect
          key={i}
          x={x(i) - innerW / n / 2}
          y={f.pad.t}
          width={innerW / n}
          height={innerH}
          fill="transparent"
          onMouseEnter={() => setHover(i)}
          onMouseLeave={() => setHover(null)}
        />
      ))}

      <line x1={f.pad.l} x2={f.w - f.pad.r} y1={y(0)} y2={y(0)} stroke={AXIS} strokeWidth={1} />
    </ChartFrame>
  );
}

/* ------------------------------------------------------------------ bar */

export function BarChart({
  data,
  title,
  height,
}: {
  data: { label: string; value: number; color?: string }[];
  title: string;
  height?: number;
}) {
  const f = { ...defaultFrame, h: 200 };
  const max = niceMax(Math.max(...data.map((d) => d.value), 1));
  const innerW = f.w - f.pad.l - f.pad.r;
  const innerH = f.h - f.pad.t - f.pad.b;
  const bw = (innerW / Math.max(data.length, 1)) * 0.56;

  return (
    <ChartFrame frame={f} title={title} height={height}>
      {[0, 0.5, 1].map((t) => (
        <line
          key={t}
          x1={f.pad.l}
          x2={f.w - f.pad.r}
          y1={f.pad.t + innerH - t * innerH}
          y2={f.pad.t + innerH - t * innerH}
          stroke={GRID}
        />
      ))}
      {data.map((d, i) => {
        const cx = f.pad.l + (i + 0.5) * (innerW / Math.max(data.length, 1));
        const h = (d.value / max) * innerH;
        return (
          <g key={d.label}>
            <rect
              x={cx - bw / 2}
              y={f.pad.t + innerH - h}
              width={bw}
              height={Math.max(h, 1)}
              rx={2}
              fill={d.color ?? "var(--geo)"}
            >
              <title>{`${d.label}: ${d.value}`}</title>
            </rect>
            <text
              x={cx}
              y={f.pad.t + innerH - h - 5}
              textAnchor="middle"
              fontSize={10}
              fill="var(--ink-2)"
              className="mono"
            >
              {d.value}
            </text>
            <text x={cx} y={f.h - 8} textAnchor="middle" fontSize={9} fill={LABEL}>
              {d.label}
            </text>
          </g>
        );
      })}
      <line
        x1={f.pad.l}
        x2={f.w - f.pad.r}
        y1={f.pad.t + innerH}
        y2={f.pad.t + innerH}
        stroke={AXIS}
      />
    </ChartFrame>
  );
}

/* ------------------------------------------------------------------ donut */

export function DonutChart({
  data,
  title,
  centerLabel,
  centerValue,
}: {
  data: { label: string; value: number; color: string }[];
  title: string;
  centerLabel?: string;
  centerValue?: string;
}) {
  const total = data.reduce((a, d) => a + d.value, 0) || 1;
  const R = 62;
  const r = 40;
  const cx = 80;
  const cy = 80;
  let angle = -Math.PI / 2;

  const arc = (start: number, end: number) => {
    const large = end - start > Math.PI ? 1 : 0;
    const p = (rad: number, radius: number) => [cx + Math.cos(rad) * radius, cy + Math.sin(rad) * radius];
    const [x1, y1] = p(start, R);
    const [x2, y2] = p(end, R);
    const [x3, y3] = p(end, r);
    const [x4, y4] = p(start, r);
    return `M${x1},${y1} A${R},${R} 0 ${large} 1 ${x2},${y2} L${x3},${y3} A${r},${r} 0 ${large} 0 ${x4},${y4} Z`;
  };

  return (
    <div className="chart-wrap">
      <svg viewBox="0 0 160 160" role="img" aria-label={title} style={{ maxHeight: 168 }}>
        {data.map((d) => {
          const sweep = (d.value / total) * Math.PI * 2;
          const path = arc(angle, angle + Math.max(sweep, 0.001));
          angle += sweep;
          return (
            <path key={d.label} d={path} fill={d.color}>
              <title>{`${d.label}: ${d.value}`}</title>
            </path>
          );
        })}
        {centerValue && (
          <text x={cx} y={cy - 2} textAnchor="middle" fontSize={22} className="mono" fill="var(--ink)">
            {centerValue}
          </text>
        )}
        {centerLabel && (
          <text x={cx} y={cy + 14} textAnchor="middle" fontSize={9} fill={LABEL}>
            {centerLabel}
          </text>
        )}
      </svg>
      <div className="chart-legend">
        {data.map((d) => (
          <span key={d.label}>
            <i style={{ background: d.color, width: 9, height: 9, borderRadius: 2 }} />
            {d.label} · {d.value}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ horizontal bars */

export function HBarChart({
  data,
  max,
  unit = "",
}: {
  data: { label: string; value: number; color?: string }[];
  max?: number;
  unit?: string;
}) {
  const m = max ?? Math.max(...data.map((d) => d.value), 1);
  return (
    <div>
      {data.map((d) => (
        <div className="hbar-row" key={d.label}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {d.label}
          </span>
          <span className="hbar-track">
            <span
              className="hbar-fill"
              style={{ width: `${(d.value / m) * 100}%`, background: d.color ?? "var(--geo)" }}
            />
          </span>
          <span className="mono" style={{ textAlign: "right" }}>
            {d.value}
            {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ calendar heatmap */

export function RiskCalendar({
  days,
}: {
  days: { date: string; riskLevel: RiskLevel; riskScore: number }[];
}) {
  return (
    <>
      <div className="cal-grid">
        {days.map((d) => (
          <span
            key={d.date}
            className="cal-cell"
            style={{ background: riskVar(d.riskLevel), opacity: 0.35 + (d.riskScore / 100) * 0.65 }}
            title={`${d.date.slice(0, 10)} — ${d.riskLevel} (${d.riskScore})`}
          />
        ))}
      </div>
      <div className="chart-legend" style={{ marginTop: 8 }}>
        {(["LOW", "MODERATE", "HIGH", "CRITICAL"] as RiskLevel[]).map((l) => (
          <span key={l}>
            <i style={{ background: riskVar(l), width: 10, height: 10, borderRadius: 2 }} />
            {l}
          </span>
        ))}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ sparkline */

export function Sparkline({
  values,
  color = "var(--geo)",
  height = 34,
}: {
  values: number[];
  color?: string;
  height?: number;
}) {
  if (!values.length) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1 || 1)) * 100},${28 - ((v - min) / range) * 26}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" style={{ width: "100%", height }} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
