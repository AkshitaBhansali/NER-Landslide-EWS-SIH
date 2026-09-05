import { useEffect, type ReactNode } from "react";
import type { AlertSeverity, ReportKpi, RiskLevel, SensorStatus } from "@/types";
import { riskBgVar, riskGlyph, riskVar } from "@/utils";
import { IconClose } from "./Icon";

/* ------------------------------------------------------------------ risk badge */

/**
 * Risk is communicated by colour AND a glyph AND the word itself, never by colour
 * alone — the accessibility requirement that matters most in an emergency UI.
 */
export function RiskBadge({
  level,
  square = false,
  title,
}: {
  level: RiskLevel | AlertSeverity;
  square?: boolean;
  title?: string;
}) {
  return (
    <span
      className={`badge${square ? " sq" : ""}`}
      style={{ background: riskBgVar(level), color: riskVar(level), borderColor: riskVar(level) }}
      title={title ?? `${level} risk`}
    >
      <span className="glyph" aria-hidden="true">
        {riskGlyph(level)}
      </span>
      {level}
    </span>
  );
}

export function Badge({ children, tone }: { children: ReactNode; tone?: "plain" | "geo" }) {
  if (tone === "geo") {
    return (
      <span
        className="badge"
        style={{ background: "var(--geo-soft)", color: "var(--geo-ink)", borderColor: "#bcd9d3" }}
      >
        {children}
      </span>
    );
  }
  return <span className="badge plain">{children}</span>;
}

/* ------------------------------------------------------------------ status */

const STATUS_COLOR: Record<SensorStatus, string> = {
  ONLINE: "var(--low)",
  DEGRADED: "var(--mod)",
  OFFLINE: "var(--sev)",
};

export function StatusIndicator({
  status,
  label,
  pulse = false,
}: {
  status: SensorStatus | "ONLINE" | "DEGRADED" | "OFFLINE";
  label?: string;
  pulse?: boolean;
}) {
  return (
    <span className="status-dot">
      <i
        className={pulse && status !== "OFFLINE" ? "pulse" : undefined}
        style={{ background: STATUS_COLOR[status] }}
      />
      <span>{label ?? status}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ cards */

export function Card({
  title,
  subtitle,
  actions,
  children,
  bodyClass = "card-body",
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  bodyClass?: string;
  id?: string;
}) {
  return (
    <section className="card" id={id}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <div className="hint">{subtitle}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

/**
 * Small provenance marker placed next to a figure whose origin is not obvious.
 *
 * This replaced a "DEMO" tag. The distinction that matters operationally is not
 * demo-versus-real but what a number is made of: a simulated reading, a historical
 * record, a model output and a citizen report each deserve a different amount of
 * trust, and one boolean could not say which was which.
 */
export type Provenance = "Simulated" | "Historical" | "Model-derived" | "Forecast" | "User-reported";

export const ProvenanceTag = ({ kind = "Simulated" }: { kind?: Provenance }) => (
  <span
    className="prov-inline"
    title={
      {
        Simulated: "Produced by the physics-informed sensor simulator, not measured in the field.",
        Historical: "From the recorded regional event dataset.",
        "Model-derived": "Computed by the risk or exposure engine.",
        Forecast: "Projected forward, not yet observed.",
        "User-reported": "Submitted from the field and pending or completed verification.",
      }[kind]
    }
  >
    {kind}
  </span>
);

export function KpiCard({
  label,
  value,
  unit,
  note,
  level,
  provenance,
  onClick,
}: {
  label: string;
  value: string | number;
  unit?: string;
  note?: ReactNode;
  level?: RiskLevel | AlertSeverity;
  provenance?: Provenance;
  onClick?: () => void;
}) {
  const body = (
    <>
      <div className="row between" style={{ gap: 6 }}>
        <span className="lab">{label}</span>
        {provenance && <ProvenanceTag kind={provenance} />}
      </div>
      <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
        <span className="val" style={level ? { color: riskVar(level) } : undefined}>
          {value}
          {unit && <span className="unit">{unit}</span>}
        </span>
        {level && <RiskBadge level={level} />}
      </div>
      {note && <div className="note">{note}</div>}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className="kpi emphasis"
        onClick={onClick}
        style={{
          borderLeftColor: level ? riskVar(level) : "var(--line-2)",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        {body}
      </button>
    );
  }

  return (
    <div className="kpi emphasis" style={{ borderLeftColor: level ? riskVar(level) : "var(--line-2)" }}>
      {body}
    </div>
  );
}

export function ReportKpiCard({ kpi }: { kpi: ReportKpi }) {
  const dir = kpi.deltaDirection ?? "FLAT";
  const good =
    dir === "FLAT"
      ? "flat"
      : (dir === "UP") === Boolean(kpi.higherIsBetter)
        ? "good"
        : "bad";
  return (
    <div className="kpi">
      <span className="lab">{kpi.label}</span>
      <span className="val">
        {kpi.value}
        {kpi.unit && <span className="unit">{kpi.unit}</span>}
      </span>
      {kpi.deltaPct !== undefined && (
        <span className={`delta ${good}`}>
          {dir === "UP" ? "▲" : dir === "DOWN" ? "▼" : "—"} {kpi.deltaPct}% vs prev. quarter
        </span>
      )}
      {kpi.note && <span className="note">{kpi.note}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ async states */

export const LoadingState = ({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) => (
  <div role="status" aria-live="polite">
    <span className="sr-only">{label}</span>
    <div className="stack" style={{ gap: 8 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: i === 0 ? 22 : 14, width: `${100 - i * 12}%` }} />
      ))}
    </div>
    <div className="tiny muted" style={{ marginTop: 8 }}>
      {label}
    </div>
  </div>
);

/**
 * The message is the product here.
 *
 * "Data unavailable" sends a duty officer to a developer. The service layer already
 * produces messages that say what is actually unreachable and what the console is
 * showing instead ("Cannot reach the monitoring service. Showing the last
 * synchronised data."), so this component leads with that rather than burying it
 * under a generic heading.
 */
export const ErrorState = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div className="state-block error" role="alert">
    <strong>{message}</strong>
    {onRetry && (
      <button className="btn sm" type="button" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);

export const EmptyState = ({ title, hint }: { title: string; hint?: string }) => (
  <div className="state-block">
    <strong>{title}</strong>
    {hint && <span>{hint}</span>}
  </div>
);

/**
 * Renders exactly one of loading / error / empty / content, so no data-driven region can
 * ever end up as a blank white area.
 */
export function AsyncSection<T>({
  state,
  children,
  loadingLabel,
  // A specific statement beats "No data available", which tells an operator nothing
  // about whether the sensor is broken, the district is quiet, or the filter is wrong.
  emptyTitle = "Nothing recorded for this scope",
  emptyHint,
  isEmpty,
  rows,
}: {
  state: { data: T | null; loading: boolean; error: string | null; reload: () => void };
  children: (data: T) => ReactNode;
  loadingLabel?: string;
  emptyTitle?: string;
  emptyHint?: string;
  isEmpty?: (data: T) => boolean;
  rows?: number;
}) {
  if (state.loading) return <LoadingState label={loadingLabel} rows={rows} />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (!state.data) return <EmptyState title={emptyTitle} hint={emptyHint} />;
  if (isEmpty?.(state.data)) return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(state.data)}</>;
}

/* ------------------------------------------------------------------ drawer */

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  footer,
  children,
  labelledBy = "drawer-title",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  labelledBy?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <header className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <h2 id={labelledBy} style={{ fontSize: 15 }}>
              {title}
            </h2>
            {subtitle && <div className="tiny muted">{subtitle}</div>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close panel" type="button">
            <IconClose size={15} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>
  );
}

/* ------------------------------------------------------------------ definition list */

export function DefRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={typeof children === "string" && children.length > 24 ? "text" : undefined}>
        {children}
      </dd>
    </>
  );
}

/* ------------------------------------------------------------------ meter */

export const Meter = ({ value, color = "var(--geo)" }: { value: number; color?: string }) => (
  <div className="meter" role="presentation">
    <i style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }} />
  </div>
);
