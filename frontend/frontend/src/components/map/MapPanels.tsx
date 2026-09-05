import type { GISLayer, GISLayerId, RiskZone, Sensor } from "@/types";
import { DefRow, Drawer, Meter, RiskBadge } from "@/components/ui/primitives";
import { formatDateTime, relativeTime, riskVar } from "@/utils";

/* ------------------------------------------------------------------ layer control */

export function MapLayerControl({
  active,
  onToggle,
  layers = [],
  compact = false,
}: {
  active: Set<GISLayerId>;
  onToggle: (id: GISLayerId) => void;
  layers?: GISLayer[];
  compact?: boolean;
}) {
  const groups = compact
    ? [{ key: "ALL", label: "Layers", items: layers }]
    : (["RISK", "ASSETS", "TERRAIN", "BASE"] as const).map((key) => ({
        key,
        label:
          key === "RISK" ? "Risk" : key === "ASSETS" ? "Assets & exposure" : key === "TERRAIN" ? "Terrain" : "Base",
        items: layers.filter((l) => l.group === key),
      }));

  return (
    <div className="layer-panel">
      {groups.map((g) =>
        g.items.length ? (
          <div key={g.key}>
            {!compact && (
              <div className="eyebrow" style={{ padding: "6px 4px 2px" }}>
                {g.label}
              </div>
            )}
            {g.items.map((layer) => (
              <label
                key={layer.id}
                className="layer-toggle"
                title={layer.sourceHint}
              >
                <input
                  type="checkbox"
                  checked={active.has(layer.id)}
                  disabled={!layer.available}
                  onChange={() => onToggle(layer.id)}
                />
                <span>
                  {layer.label}
                  {!compact && <span className="lt-desc">{layer.description}</span>}
                </span>
              </label>
            ))}
          </div>
        ) : null,
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ zone detail */

const FACTOR_LABEL: Record<string, string> = {
  slope_deg: "Slope",
  rainfall_24h_mm: "Rainfall 24h",
  rainfall_72h_mm: "Rainfall 72h",
  rainfall_7d_mm: "Rainfall 7d",
  antecedent_precip_index: "Antecedent precip.",
  soil_moisture_pct: "Soil moisture",
};

export function ZoneDetailPanel({
  zone,
  sensors,
  open,
  onClose,
  onViewAlerts,
  onOpenGis,
}: {
  zone: RiskZone | null;
  sensors: Sensor[];
  open: boolean;
  onClose: () => void;
  onViewAlerts?: () => void;
  onOpenGis?: () => void;
}) {
  if (!zone) return null;
  const zoneSensors = sensors.filter((s) => s.zoneId === zone.id);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={zone.name}
      subtitle={`${zone.district} · updated ${relativeTime(zone.updatedAt)}`}
      footer={
        <>
          {onViewAlerts && (
            <button className="btn primary" type="button" onClick={onViewAlerts}>
              View alerts for this zone
            </button>
          )}
          {onOpenGis && (
            <button className="btn" type="button" onClick={onOpenGis}>
              Open in GIS
            </button>
          )}
        </>
      }
    >
      <div className="row between" style={{ marginBottom: 10 }}>
        <RiskBadge level={zone.riskLevel} />
        <span className="mono" style={{ fontSize: 22, color: riskVar(zone.riskLevel), fontWeight: 600 }}>
          {zone.riskScore}
          <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
            /100
          </span>
        </span>
      </div>

      {zone.expectedWindowHours && (
        <div className="recommend" style={{ marginBottom: 12 }}>
          Expected onset window: next {zone.expectedWindowHours} hours.
        </div>
      )}

      <dl className="dl">
        <DefRow label="District">{zone.district}</DefRow>
        <DefRow label="Location">
          {zone.center.lat.toFixed(3)}, {zone.center.lng.toFixed(3)}
        </DefRow>
        <DefRow label="Probability">{(zone.probability * 100).toFixed(1)}%</DefRow>
        <DefRow label="Rainfall 24h">{zone.rainfall24h} mm</DefRow>
        <DefRow label="Rainfall 72h">{zone.rainfall72h} mm</DefRow>
        <DefRow label="Rainfall 7d">{zone.rainfall7d} mm</DefRow>
        <DefRow label="Soil moisture">{zone.soilMoisture}% VWC</DefRow>
        <DefRow label="Slope">{zone.slope}°</DefRow>
        <DefRow label="Elevation">{zone.elevation} m</DefRow>
        <DefRow label="Aspect">{zone.aspect}°</DefRow>
        <DefRow label="Sensor confidence">{zone.sensorConfidence}/100</DefRow>
        <DefRow label="Population">{zone.population.toLocaleString("en-IN")}</DefRow>
        <DefRow label="Last updated">{formatDateTime(zone.updatedAt)}</DefRow>
      </dl>

      <h3 style={{ fontSize: 12.5, margin: "16px 0 6px" }}>Contributing factors</h3>
      <div className="stack" style={{ gap: 6 }}>
        {Object.entries(zone.contributingFactors)
          .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
          .map(([k, v]) => (
            <div key={k}>
              <div className="row between tiny">
                <span>{FACTOR_LABEL[k] ?? k}</span>
                <span className="mono">{((v ?? 0) * 100).toFixed(1)}%</span>
              </div>
              <Meter value={(v ?? 0) * 100} />
            </div>
          ))}
      </div>
      <div className="tiny muted" style={{ marginTop: 6 }}>
        Factor weights come from the model's own feature attribution, not a fixed formula.
      </div>

      <h3 style={{ fontSize: 12.5, margin: "16px 0 6px" }}>
        Sensors feeding this zone ({zoneSensors.length})
      </h3>
      {zoneSensors.length ? (
        <div className="stack" style={{ gap: 5 }}>
          {zoneSensors.map((s) => (
            <div key={s.id} className="row between tiny" style={{ borderBottom: "1px dotted var(--line-2)", paddingBottom: 4 }}>
              <span className="mono">{s.id}</span>
              <span>
                {s.reading} {s.unit}
              </span>
              <span
                style={{
                  color:
                    s.status === "ONLINE" ? "var(--low)" : s.status === "DEGRADED" ? "var(--mod)" : "var(--sev)",
                  fontWeight: 600,
                }}
              >
                {s.status}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="tiny muted">No instruments assigned to this zone yet.</div>
      )}

      <h3 style={{ fontSize: 12.5, margin: "16px 0 6px" }}>Exposure</h3>
      <div className="tiny">
        <strong>Roads:</strong> {zone.nearbyRoads.join(", ") || "—"}
      </div>
      <div className="tiny" style={{ marginTop: 3 }}>
        <strong>Villages:</strong> {zone.nearbyVillages.join(", ") || "—"}
      </div>

      <div className="recommend" style={{ marginTop: 14 }}>
        <strong style={{ display: "block", fontSize: 11, letterSpacing: "0.07em", textTransform: "uppercase" }}>
          Recommended action
        </strong>
        {zone.recommendedAction}
      </div>

      <div className="disclaimer">
        Sensor values are simulated telemetry and risk scores are model-derived. They are not
        observations and must not be used for operational decisions.
      </div>
    </Drawer>
  );
}
