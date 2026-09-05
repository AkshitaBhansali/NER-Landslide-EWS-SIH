import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { useApp } from "@/state/AppContext";
import { formatDateTime, relativeTime } from "@/utils";

export function PageHeader({
  title,
  subtitle,
  actions,
  updatedAt,
  freshnessMinutes,
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
  updatedAt?: string | null;
  freshnessMinutes?: number;
}) {
  const app = useApp();
  return (
    <header className="page-head">
      <div style={{ minWidth: 0 }}>
        <h1>{title}</h1>
        <div className="sub">{subtitle}</div>
        <div className="meta-strip">
          <span>
            <span className="k">Scope</span>
            <strong>{app.scopeLabel}</strong>
          </span>
          {updatedAt && (
            <span>
              <span className="k">Last updated</span>
              <span className="mono">{formatDateTime(updatedAt)}</span>{" "}
              <span className="muted">({relativeTime(updatedAt)})</span>
            </span>
          )}
          {freshnessMinutes !== undefined && (
            <span>
              <span className="k">Data freshness</span>
              <span className="mono">{freshnessMinutes} min</span>
            </span>
          )}
          <span>
            <span className="k">System</span>
            <span style={{ color: app.connection === "ONLINE" ? "var(--low)" : "var(--sev)", fontWeight: 600 }}>
              {app.connection === "ONLINE" ? "Operational" : "Offline mode"}
            </span>
          </span>
        </div>
      </div>
      {actions && <div className="row noprint">{actions}</div>}
    </header>
  );
}

export interface PipelineStat {
  /** Stage of the warning chain, e.g. "Sensors" or "Alerts". */
  name: string;
  /** The live number this stage is currently producing. */
  value: string;
  to: string;
}

/**
 * The warning chain as one strip: sensors -> data quality -> risk -> alerts.
 *
 * Each step carries the number that stage is producing right now, so an operator can
 * see at a glance where the chain has stopped — "0/12 reporting" at the first step
 * explains a quiet alerts page far faster than checking four screens.
 *
 * Stages are named for what they do, not for who built them. Developer and workstream
 * names were removed: on an operational disaster-management console they are noise at
 * best, and at worst they imply a person is accountable for a live number at 3am.
 */
export function PipelineStrip({ steps }: { steps: PipelineStat[] }) {
  return (
    <nav className="pipeline" aria-label="Warning chain status">
      {steps.map((s) => (
        <Link key={s.name} to={s.to} className="pipe-step">
          <div className="name">{s.name}</div>
          <div className="val">{s.value}</div>
        </Link>
      ))}
    </nav>
  );
}
