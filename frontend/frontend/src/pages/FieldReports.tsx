import { useMemo, useState } from "react";
import type { IncidentReport, ReportSyncStatus } from "@/types";
import { useApp } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { incidentService } from "@/services";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, DefRow, Drawer, EmptyState, KpiCard, RiskBadge } from "@/components/ui/primitives";
import { FieldReportForm } from "@/components/fieldreports/FieldReportForm";
import { formatDateTime, matchesQuery, relativeTime, titleCase } from "@/utils";

const SYNC_STYLE: Record<ReportSyncStatus, { label: string; color: string }> = {
  SYNCED: { label: "Synced", color: "var(--low)" },
  PENDING_SYNC: { label: "Pending sync", color: "var(--mod)" },
  FAILED: { label: "Sync failed", color: "var(--sev)" },
};

export function FieldReports() {
  const app = useApp();
  const [local, setLocal] = useState<IncidentReport[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"ALL" | "PENDING" | "VERIFIED" | "OFFLINE">("ALL");
  const [detail, setDetail] = useState<IncidentReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reports = useAsync(() => incidentService.getFieldReports(app.scope), [app.stateCode, app.districtId]);

  // Locally submitted reports appear immediately, ahead of the service round-trip.
  const all = useMemo(() => {
    const server = reports.data ?? [];
    const ids = new Set(server.map((r) => r.id));
    return [...local.filter((r) => !ids.has(r.id)), ...server];
  }, [reports.data, local]);

  const filtered = useMemo(() => {
    let list = all;
    if (filter === "PENDING") list = list.filter((r) => r.verification === "PENDING");
    if (filter === "VERIFIED") list = list.filter((r) => r.verification === "VERIFIED");
    if (filter === "OFFLINE") list = list.filter((r) => r.syncStatus !== "SYNCED");
    if (query.trim())
      list = list.filter((r) => matchesQuery(query, r.id, r.description, r.district, r.roadOrVillage));
    return list;
  }, [all, filter, query]);

  const pending = all.filter((r) => r.verification === "PENDING").length;
  const queued = all.filter((r) => r.syncStatus === "PENDING_SYNC").length;

  const verify = async (r: IncidentReport, decision: "VERIFIED" | "REJECTED") => {
    setBusy(r.id);
    try {
      await incidentService.setVerification(r.id, decision);
      setLocal((prev) => prev.map((x) => (x.id === r.id ? { ...x, verification: decision } : x)));
      reports.reload();
      setDetail(null);
      app.toast({
        tone: decision === "VERIFIED" ? "success" : "info",
        title: `${r.id} ${decision.toLowerCase()}`,
        body: decision === "VERIFIED" ? "Added to the incident record and the map." : "Marked as not actionable.",
      });
    } finally {
      setBusy(null);
    }
  };

  const retry = async (r: IncidentReport) => {
    setBusy(r.id);
    try {
      const { synced, remaining } = await incidentService.syncQueue();
      setLocal((prev) => prev.map((x) => (x.id === r.id ? { ...x, syncStatus: "SYNCED" } : x)));
      reports.reload();
      app.toast({
        tone: synced > 0 ? "success" : "warning",
        title: synced > 0 ? `${synced} report(s) uploaded` : "Still offline",
        body:
          remaining > 0
            ? `${remaining} report(s) still queued on this device.`
            : "The device queue is empty.",
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Field Reports"
        subtitle="Citizen and field-officer observations of cracks, slope movement and blocked roads"
        updatedAt={reports.fetchedAt}
      />

      <div className="stack">
        <div className="grid grid-4">
          <KpiCard label="Reports received" value={all.length} note="In the selected scope" />
          <KpiCard label="Pending verification" value={pending} level={pending > 0 ? "MODERATE" : "LOW"} />
          <KpiCard label="Queued for sync" value={queued} note="Saved offline, awaiting connectivity" />
          <KpiCard
            label="Connection"
            value={app.connection === "ONLINE" ? "Online" : "Offline"}
            level={app.connection === "ONLINE" ? "LOW" : "MODERATE"}
            note={app.connection === "ONLINE" ? "Submissions upload immediately" : "Submissions will queue locally"}
          />
        </div>

        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.05fr) minmax(0, 1fr)", gap: 12 }}>
          <Card title="Submit a report" subtitle="Designed for one-handed use in the field">
            <FieldReportForm onSubmitted={(r) => setLocal((prev) => [r, ...prev])} />
          </Card>

          <section className="card">
            <div className="toolbar">
              <input
                type="search"
                placeholder="Search reports…"
                aria-label="Search reports"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{ flex: "1 1 150px" }}
              />
              <div className="segmented">
                {(["ALL", "PENDING", "VERIFIED", "OFFLINE"] as const).map((f) => (
                  <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                    {titleCase(f)}
                  </button>
                ))}
              </div>
            </div>

            <div className="card-body">
              <AsyncSection
                state={reports}
                loadingLabel="Loading report queue…"
                emptyTitle="No reports yet"
                emptyHint="Submitted reports appear here for verification."
                isEmpty={() => all.length === 0}
                rows={4}
              >
                {() =>
                  filtered.length === 0 ? (
                    <EmptyState title="No reports match this filter" />
                  ) : (
                    <div className="stack" style={{ gap: 9 }}>
                      {filtered.map((r) => (
                        <button
                          key={r.id}
                          type="button"
                          className="card soft"
                          style={{ padding: "10px 12px", textAlign: "left", cursor: "pointer", border: "1px solid var(--line)" }}
                          onClick={() => setDetail(r)}
                        >
                          <div className="row between">
                            <span className="row" style={{ gap: 7 }}>
                              <RiskBadge level={r.severity} />
                              <span className="mono tiny muted">{r.id}</span>
                            </span>
                            <span className="tiny" style={{ color: SYNC_STYLE[r.syncStatus].color, fontWeight: 600 }}>
                              ● {SYNC_STYLE[r.syncStatus].label}
                            </span>
                          </div>
                          <div style={{ fontSize: 13, fontWeight: 500, marginTop: 5 }}>
                            {titleCase(r.incidentType)} · {r.roadOrVillage}
                          </div>
                          <div className="tiny muted" style={{ marginTop: 2 }}>
                            {r.district} · {titleCase(r.reporterType)} · {relativeTime(r.reportedAt)}
                            {r.media.length > 0 && ` · ${r.media.length} attachment(s)`}
                          </div>
                          <div
                            className="tiny"
                            style={{
                              marginTop: 5,
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                            }}
                          >
                            {r.description}
                          </div>
                          <div className="row" style={{ gap: 6, marginTop: 6 }}>
                            <span className="tag">{r.verification}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )
                }
              </AsyncSection>
            </div>
          </section>
        </div>

        <div className="callout">
          <strong>Offline behaviour.</strong> This interface models sync state only: a report saved
          offline is held as <span className="mono">PENDING_SYNC</span> and flushed by the PWA
          background-sync layer, which owns IndexedDB persistence and retry policy.
        </div>
      </div>

      <Drawer
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={detail ? `${detail.id} · ${titleCase(detail.incidentType)}` : ""}
        subtitle={detail ? `${detail.roadOrVillage} · ${detail.district}` : undefined}
        labelledBy="report-detail-title"
        footer={
          detail && (
            <>
              <button
                className="btn primary"
                type="button"
                disabled={busy === detail.id || detail.verification === "VERIFIED"}
                onClick={() => void verify(detail, "VERIFIED")}
              >
                Verify report
              </button>
              <button
                className="btn"
                type="button"
                disabled={busy === detail.id || detail.verification === "REJECTED"}
                onClick={() => void verify(detail, "REJECTED")}
              >
                Reject
              </button>
              {detail.syncStatus !== "SYNCED" && (
                <button className="btn" type="button" disabled={busy === detail.id} onClick={() => void retry(detail)}>
                  Retry sync
                </button>
              )}
            </>
          )
        }
      >
        {detail && (
          <>
            <div className="row between" style={{ marginBottom: 10 }}>
              <RiskBadge level={detail.severity} />
              <span className="tiny" style={{ color: SYNC_STYLE[detail.syncStatus].color, fontWeight: 600 }}>
                ● {SYNC_STYLE[detail.syncStatus].label}
              </span>
            </div>
            <p style={{ fontSize: 13 }}>{detail.description}</p>
            <dl className="dl">
              <DefRow label="Incident type">{titleCase(detail.incidentType)}</DefRow>
              <DefRow label="District">{detail.district}</DefRow>
              <DefRow label="Road / village">{detail.roadOrVillage}</DefRow>
              <DefRow label="Reported by">
                {titleCase(detail.reporterType)}
                {detail.reporterName ? ` · ${detail.reporterName}` : ""}
              </DefRow>
              <DefRow label="Reported at">{formatDateTime(detail.reportedAt)}</DefRow>
              <DefRow label="Location">
                {detail.location ? `${detail.location.lat.toFixed(5)}, ${detail.location.lng.toFixed(5)}` : "Not captured"}
              </DefRow>
              <DefRow label="Verification">{detail.verification}</DefRow>
            </dl>

            {detail.media.length > 0 && (
              <>
                <h3 style={{ fontSize: 12.5, margin: "14px 0 6px" }}>Attachments</h3>
                <div className="media-grid">
                  {detail.media.map((m) => (
                    <div className="media-item" key={m.id}>
                      {m.kind === "IMAGE" ? (
                        <img src={m.previewUrl} alt={m.name} />
                      ) : (
                        <video src={m.previewUrl} controls playsInline />
                      )}
                      <span className="fname">{m.name}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}
