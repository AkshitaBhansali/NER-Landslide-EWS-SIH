import { useState } from "react";
import { useApp } from "@/state/AppContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, StatusIndicator } from "@/components/ui/primitives";
import { RegionSelector } from "@/components/layout/DashboardLayout";
import { API_BASE_URL } from "@/services/api";
import { systemService } from "@/services";
import { useAsync } from "@/state/useAsync";

const LANGUAGES = [
  "English",
  "Assamese (অসমীয়া)",
  "Bengali (বাংলা)",
  "Bodo (बड़ो)",
  "Khasi",
  "Mizo",
  "Manipuri (মৈতৈলোন্)",
  "Nepali (नेपाली)",
  "Nagamese",
];

export function Settings() {
  const app = useApp();
  const status = useAsync(() => systemService.getSystemStatus(), [app.clockTick]);
  const [thresholds, setThresholds] = useState({ critical: 80, high: 60, moderate: 35, rainfall: 95 });
  const [channels, setChannels] = useState({ inApp: true, sms: true, email: false, siren: false });
  const [language, setLanguage] = useState("English");
  const [offline, setOffline] = useState({ autoSync: true, cacheMaps: true, lowData: false });

  return (
    <>
      <PageHeader title="Settings" subtitle="Alert thresholds, notification channels, language and offline behaviour" />

      <div className="stack">
        <div className="grid grid-2 grid-1-mobile">
          <Card title="Default region" subtitle="Applied to every page on load">
            <RegionSelector />
            <p className="tiny muted" style={{ marginTop: 10 }}>
              Currently viewing <strong>{app.scopeLabel}</strong>. Changing the scope re-queries every
              module through the service layer.
            </p>
          </Card>

          <Card title="Language" subtitle="Multilingual notifications for local communities">
            <label className="field">
              Interface and alert language
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </label>
            <div className="callout info" style={{ marginTop: 10 }}>
              Translation strings are not bundled in this prototype. The selector records the preference
              so the notification service can send SMS in the recipient's language once localisation
              files land.
            </div>
          </Card>
        </div>

        <Card
          title="Alert thresholds"
          subtitle="Score at which each severity is raised"
          actions={
            <button
              className="btn sm primary"
              type="button"
              onClick={() =>
                app.toast({
                  tone: "success",
                  title: "Thresholds saved locally",
                  body: "Persisted server-side once the configuration API is available.",
                })
              }
            >
              Save thresholds
            </button>
          }
        >
          <div className="grid grid-4">
            {[
              ["critical", "Critical at or above", thresholds.critical, "var(--sev)"],
              ["high", "High at or above", thresholds.high, "var(--high)"],
              ["moderate", "Moderate at or above", thresholds.moderate, "var(--mod)"],
              ["rainfall", "Rainfall alert (mm/24h)", thresholds.rainfall, "var(--info)"],
            ].map(([key, label, value, color]) => (
              <div key={String(key)} className="card soft" style={{ padding: "10px 12px" }}>
                <div className="eyebrow">{label}</div>
                <div className="row" style={{ gap: 8, marginTop: 4 }}>
                  <input
                    type="range"
                    min={key === "rainfall" ? 40 : 5}
                    max={key === "rainfall" ? 250 : 100}
                    value={Number(value)}
                    onChange={(e) =>
                      setThresholds((t) => ({ ...t, [String(key)]: Number(e.target.value) }))
                    }
                    aria-label={String(label)}
                    style={{ flex: 1, minHeight: 0 }}
                  />
                  <span className="mono" style={{ fontSize: 16, fontWeight: 600, color: String(color) }}>
                    {String(value)}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <div className="tiny muted" style={{ marginTop: 10 }}>
            Lowering a threshold increases recall and false alarms together. The current model already
            favours recall (0.850) over precision (0.549).
          </div>
        </Card>

        <div className="grid grid-2 grid-1-mobile">
          <Card title="Notification channels">
            <div className="stack" style={{ gap: 6 }}>
              {([
                ["inApp", "In-app notifications"],
                ["sms", "SMS to district officers"],
                ["email", "Email digest"],
                ["siren", "Community siren trigger (critical only)"],
              ] as const).map(([key, label]) => (
                <label key={key} className="layer-toggle">
                  <input
                    type="checkbox"
                    checked={channels[key]}
                    onChange={() => setChannels((c) => ({ ...c, [key]: !c[key] }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
            <div className="tiny muted" style={{ marginTop: 8 }}>
              Delivery is owned by the alert engine. These toggles record intent only.
            </div>
          </Card>

          <Card title="Offline &amp; low-network">
            <div className="stack" style={{ gap: 6 }}>
              {([
                ["autoSync", "Auto-sync queued field reports when connectivity returns"],
                ["cacheMaps", "Cache the last map view for offline use"],
                ["lowData", "Low-data mode (skip imagery layers)"],
              ] as const).map(([key, label]) => (
                <label key={key} className="layer-toggle">
                  <input
                    type="checkbox"
                    checked={offline[key]}
                    onChange={() => setOffline((o) => ({ ...o, [key]: !o[key] }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
            <div className="row between" style={{ marginTop: 10 }}>
              <span className="tiny muted">Simulate connectivity for testing:</span>
              <div className="segmented">
                {(["ONLINE", "OFFLINE"] as const).map((c) => (
                  <button
                    key={c}
                    type="button"
                    aria-pressed={app.connection === c}
                    onClick={() => {
                      app.setConnection(c);
                      app.toast({
                        tone: c === "ONLINE" ? "success" : "warning",
                        title: c === "ONLINE" ? "Connected" : "Offline mode",
                        body:
                          c === "ONLINE"
                            ? "Queued reports would now sync."
                            : "New field reports will be held locally until connectivity returns.",
                      });
                    }}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>
          </Card>
        </div>

        <Card
          title="System status"
          subtitle="What the platform can currently do, reported by the services themselves"
        >
          <AsyncSection state={status} loadingLabel="Checking services…" rows={4}>
            {(st) => (
              <>
                <div className="table-wrap">
                  <table className="data" style={{ minWidth: 560 }}>
                    <thead>
                      <tr>
                        <th scope="col">Service</th>
                        <th scope="col">Status</th>
                        <th scope="col">Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {st.services.map((svc) => (
                        <tr key={svc.name}>
                          <td>{svc.name}</td>
                          <td>
                            <StatusIndicator
                              status={svc.status === "OPERATIONAL" ? "ONLINE" : "DEGRADED"}
                              label={svc.status === "OPERATIONAL" ? "Operational" : svc.status}
                            />
                          </td>
                          <td className="tiny muted">{svc.detail ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="callout" style={{ marginTop: 12 }}>
                  API base <span className="mono">{API_BASE_URL}</span> · data provenance{" "}
                  <span className="mono">{st.dataConfidence}</span>. Sensor telemetry on this
                  deployment is produced by the physics-informed simulator; risk scores and
                  exposure rankings are model-derived; recorded events come from the historical
                  dataset. Nothing shown here is a field measurement.
                </div>
              </>
            )}
          </AsyncSection>
        </Card>
      </div>
    </>
  );
}
