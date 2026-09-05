import type { Alert, AlertStatus } from "@/types";
import { RiskBadge } from "@/components/ui/primitives";
import { formatDateTime, relativeTime, riskVar, titleCase } from "@/utils";

const STATUS_LABEL: Record<AlertStatus, string> = {
  NEW: "New",
  ACKNOWLEDGED: "Acknowledged",
  IN_PROGRESS: "Response in progress",
  RESOLVED: "Resolved",
};

const STATUS_COLOR: Record<AlertStatus, string> = {
  NEW: "var(--sev)",
  ACKNOWLEDGED: "var(--mod)",
  IN_PROGRESS: "var(--info)",
  RESOLVED: "var(--low)",
};

export function AlertCard({
  alert,
  onAcknowledge,
  onDispatch,
  onViewMap,
  onDetails,
  busy,
}: {
  alert: Alert;
  onAcknowledge?: (a: Alert) => void;
  onDispatch?: (a: Alert) => void;
  onViewMap?: (a: Alert) => void;
  onDetails?: (a: Alert) => void;
  busy?: boolean;
}) {
  return (
    <article className="alert-card" style={{ borderLeftColor: riskVar(alert.severity) }}>
      <div className="ac-top">
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 7 }}>
            <RiskBadge level={alert.severity} />
            <span className="mono tiny muted">{alert.id}</span>
            <span className="tiny" style={{ color: STATUS_COLOR[alert.status], fontWeight: 600 }}>
              ● {STATUS_LABEL[alert.status]}
            </span>
          </div>
          <h3 style={{ marginTop: 5 }}>{alert.title}</h3>
          <div className="ac-loc">
            {alert.location} · {alert.district}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="mono" style={{ fontSize: 21, fontWeight: 600, color: riskVar(alert.severity) }}>
            {alert.riskScore}
          </div>
          <div className="tiny muted">risk score</div>
        </div>
      </div>

      <div className="ac-grid">
        <span>
          <span className="k">Issued</span>
          <span className="v" title={formatDateTime(alert.issuedAt)}>
            {relativeTime(alert.issuedAt)}
          </span>
        </span>
        <span>
          <span className="k">Probability</span>
          <span className="v">{(alert.probability * 100).toFixed(0)}%</span>
        </span>
        <span>
          <span className="k">Window</span>
          <span className="v">{alert.expectedWindowHours} h</span>
        </span>
        <span>
          <span className="k">Sensor conf.</span>
          <span className="v">{alert.sensorConfidence}/100</span>
        </span>
        <span>
          <span className="k">Population</span>
          <span className="v">{alert.populationAffected.toLocaleString("en-IN")}</span>
        </span>
        <span>
          <span className="k">Trigger</span>
          <span className="v" style={{ fontSize: 11.5 }}>
            {titleCase(alert.trigger)}
          </span>
        </span>
      </div>

      <div className="tiny muted">{alert.triggerDetail}</div>

      <div className="tiny">
        <strong>Roads:</strong> {alert.affectedRoads.join(", ") || "—"} · <strong>Villages:</strong>{" "}
        {alert.affectedVillages.join(", ") || "—"}
      </div>

      <div className="recommend">{alert.recommendedAction}</div>

      <div className="ac-actions noprint">
        {onViewMap && (
          <button className="btn sm" type="button" onClick={() => onViewMap(alert)}>
            View on map
          </button>
        )}
        {onAcknowledge && (
          <button
            className="btn sm"
            type="button"
            disabled={busy || alert.status !== "NEW"}
            onClick={() => onAcknowledge(alert)}
          >
            {alert.status === "NEW" ? "Acknowledge" : "Acknowledged"}
          </button>
        )}
        {onDispatch && (
          <button
            className="btn sm primary"
            type="button"
            disabled={busy || alert.status === "IN_PROGRESS" || alert.status === "RESOLVED"}
            onClick={() => onDispatch(alert)}
          >
            Dispatch response
          </button>
        )}
        {onDetails && (
          <button className="btn sm ghost" type="button" onClick={() => onDetails(alert)}>
            View details
          </button>
        )}
      </div>
    </article>
  );
}

export function EmergencyBanner({
  alert,
  onViewMap,
  onAcknowledge,
  onDispatch,
  onDetails,
}: {
  alert: Alert;
  onViewMap: () => void;
  onAcknowledge: () => void;
  onDispatch: () => void;
  onDetails: () => void;
}) {
  return (
    <div className="emergency-banner" role="alert">
      <div className="eb-main">
        <h2>
          <span aria-hidden="true">▲▲</span> CRITICAL ALERT — {alert.title}
        </h2>
        <div className="eb-meta">
          <span>
            <strong>{alert.district}</strong> · {alert.location}
          </span>
          <span className="mono">Risk score: {alert.riskScore}</span>
          <span className="mono">Probability: {(alert.probability * 100).toFixed(0)}%</span>
          <span className="mono">Expected window: next {alert.expectedWindowHours} hours</span>
          <span className="mono">Issued {relativeTime(alert.issuedAt)}</span>
        </div>
        <div className="tiny" style={{ marginTop: 6, color: "#6d2a26" }}>
          {alert.recommendedAction}
        </div>
      </div>
      <div className="eb-actions noprint">
        <button className="btn sm" type="button" onClick={onViewMap}>
          View on map
        </button>
        <button className="btn sm" type="button" onClick={onAcknowledge} disabled={alert.status !== "NEW"}>
          Acknowledge
        </button>
        <button className="btn sm danger" type="button" onClick={onDispatch}>
          Dispatch response
        </button>
        <button className="btn sm ghost" type="button" onClick={onDetails}>
          Details
        </button>
      </div>
    </div>
  );
}
