import { useMemo, useState } from "react";
import type { Sensor, SensorStatus } from "@/types";
import { sensorTypeLabel } from "@/data/sensorTypes";
import { DefRow, Drawer, Meter, StatusIndicator } from "@/components/ui/primitives";
import { Sparkline } from "@/components/charts";
import { useAsync } from "@/state/useAsync";
import { sensorService } from "@/services";
import { formatDateTime, relativeTime, sortBy } from "@/utils";

const statusColor = (s: SensorStatus) =>
  s === "ONLINE" ? "var(--low)" : s === "DEGRADED" ? "var(--mod)" : "var(--sev)";

export function SensorCard({ sensor, onOpen }: { sensor: Sensor; onOpen: (s: Sensor) => void }) {
  return (
    <button className="sensor-card" type="button" onClick={() => onOpen(sensor)}>
      <div className="row between">
        <span className="sc-id">{sensor.id}</span>
        <StatusIndicator status={sensor.status} pulse={sensor.status === "ONLINE"} />
      </div>
      <div>
        <div className="tiny muted">{sensorTypeLabel(sensor.type)}</div>
        <div className="sc-reading">
          {sensor.status === "OFFLINE" ? "—" : sensor.reading}
          <small> {sensor.unit}</small>
        </div>
      </div>
      <div className="tiny muted" style={{ marginTop: -3 }}>
        {sensor.district} · {sensor.name.split(" · ")[0]}
      </div>
      <div>
        <div className="row between tiny">
          <span>Health</span>
          <span className="mono">{sensor.healthScore}/100</span>
        </div>
        <Meter value={sensor.healthScore} color={statusColor(sensor.status)} />
      </div>
      <div className="row between tiny muted">
        <span>Battery {sensor.batteryPct}%</span>
        <span>{sensor.rssiDbm} dBm</span>
        <span>{relativeTime(sensor.lastSeen)}</span>
      </div>
    </button>
  );
}

type SortKey = "id" | "district" | "type" | "healthScore" | "batteryPct" | "lastSeen" | "riskContribution";

export function SensorTable({ sensors, onOpen }: { sensors: Sensor[]; onOpen: (s: Sensor) => void }) {
  const [sortKey, setSortKey] = useState<SortKey>("healthScore");
  const [dir, setDir] = useState<"asc" | "desc">("asc");

  const rows = useMemo(
    () =>
      sortBy(
        sensors,
        (s) => {
          const v = s[sortKey];
          return typeof v === "number" ? v : String(v);
        },
        dir,
      ),
    [sensors, sortKey, dir],
  );

  const th = (key: SortKey, label: string) => (
    <th scope="col" aria-sort={sortKey === key ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => {
          if (sortKey === key) setDir(dir === "asc" ? "desc" : "asc");
          else {
            setSortKey(key);
            setDir("asc");
          }
        }}
      >
        {label}
        <span aria-hidden="true">{sortKey === key ? (dir === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {th("id", "Sensor ID")}
            <th scope="col">Location</th>
            {th("type", "Type")}
            <th scope="col">Reading</th>
            {th("healthScore", "Health")}
            {th("batteryPct", "Battery")}
            <th scope="col">Signal</th>
            {th("lastSeen", "Last seen")}
            {th("riskContribution", "Risk contrib.")}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className="clickable" onClick={() => onOpen(s)} tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && onOpen(s)}>
              <td className="mono">{s.id}</td>
              <td>
                {s.district}
                <div className="tiny muted">{s.name.split(" · ")[0]}</div>
              </td>
              <td>{sensorTypeLabel(s.type)}</td>
              <td className="mono">{s.status === "OFFLINE" ? "—" : `${s.reading} ${s.unit}`}</td>
              <td>
                <StatusIndicator status={s.status} label={`${s.healthScore} · ${s.status}`} />
              </td>
              <td className="mono" style={{ color: s.batteryPct < 25 ? "var(--sev)" : undefined }}>
                {s.batteryPct}%
              </td>
              <td className="mono" style={{ color: s.rssiDbm < -105 ? "var(--mod)" : undefined }}>
                {s.rssiDbm} dBm
              </td>
              <td className="mono tiny">{relativeTime(s.lastSeen)}</td>
              <td className="mono">{(s.riskContribution * 100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SensorDetailDrawer({
  sensor,
  open,
  onClose,
}: {
  sensor: Sensor | null;
  open: boolean;
  onClose: () => void;
}) {
  const readings = useAsync(
    () => sensorService.getSensorReadings(sensor?.id ?? ""),
    [sensor?.id],
    { immediate: Boolean(sensor && open) },
  );

  if (!sensor) return null;
  const sub = sensor.healthSubScores;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={sensor.id}
      subtitle={`${sensorTypeLabel(sensor.type)} · ${sensor.district}`}
      labelledBy="sensor-title"
    >
      <div className="row between" style={{ marginBottom: 12 }}>
        <StatusIndicator status={sensor.status} pulse={sensor.status === "ONLINE"} />
        <span className="mono" style={{ fontSize: 22, fontWeight: 600 }}>
          {sensor.status === "OFFLINE" ? "—" : sensor.reading}
          <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
            {" "}
            {sensor.unit}
          </span>
        </span>
      </div>

      <div className="card soft" style={{ padding: "8px 10px", marginBottom: 12 }}>
        <div className="eyebrow">Last 24 hours</div>
        {readings.loading ? (
          <div className="skeleton" style={{ height: 34 }} />
        ) : readings.data && readings.data.length ? (
          <Sparkline values={readings.data.map((r) => r.value)} color="var(--geo)" />
        ) : (
          <div className="tiny muted">Waiting for sensor data…</div>
        )}
      </div>

      <dl className="dl">
        <DefRow label="Location">{sensor.name.split(" · ")[0]}</DefRow>
        <DefRow label="Coordinates">
          {sensor.location.lat.toFixed(3)}, {sensor.location.lng.toFixed(3)}
        </DefRow>
        <DefRow label="Zone">{sensor.zoneId}</DefRow>
        <DefRow label="Health score">{sensor.healthScore}/100</DefRow>
        <DefRow label="Battery">{sensor.batteryPct}%</DefRow>
        <DefRow label="Signal">{sensor.rssiDbm} dBm</DefRow>
        <DefRow label="Reporting interval">{sensor.expectedIntervalSec / 60} min</DefRow>
        <DefRow label="Last seen">{formatDateTime(sensor.lastSeen)}</DefRow>
        <DefRow label="Installed">{formatDateTime(sensor.installedOn)}</DefRow>
        <DefRow label="Risk contribution">{(sensor.riskContribution * 100).toFixed(0)}%</DefRow>
      </dl>

      <h3 style={{ fontSize: 12.5, margin: "16px 0 6px" }}>Health breakdown</h3>
      <div className="stack" style={{ gap: 6 }}>
        {[
          ["Completeness", sub.completeness, 0.25],
          ["Validity", sub.validity, 0.25],
          ["Stability", sub.stability, 0.2],
          ["Noise", sub.noise, 0.15],
          ["Comms", sub.comms, 0.15],
        ].map(([label, value, weight]) => (
          <div key={String(label)}>
            <div className="row between tiny">
              <span>
                {label} <span className="muted">· weight {Number(weight) * 100}%</span>
              </span>
              <span className="mono">{(Number(value) * 100).toFixed(0)}</span>
            </div>
            <Meter value={Number(value) * 100} color={statusColor(sensor.status)} />
          </div>
        ))}
      </div>

      {sensor.maintenanceNote && (
        <div className="callout" style={{ marginTop: 12 }}>
          <strong>Maintenance:</strong> {sensor.maintenanceNote}
        </div>
      )}

      <div className="disclaimer">
        Health scoring follows the platform's weighted model (completeness, validity, stability,
        noise, comms). Readings shown are synthetic.
      </div>
    </Drawer>
  );
}
