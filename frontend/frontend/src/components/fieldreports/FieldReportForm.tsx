import { useState } from "react";
import type { IncidentReport, IncidentType, LatLng, MediaAttachment, ReporterType, RiskLevel } from "@/types";
import { DISTRICTS, districtById } from "@/data/regions";
import { incidentService } from "@/services";
import { useApp } from "@/state/AppContext";
import { FileUploader } from "./FileUploader";
import { IconPin } from "@/components/ui/Icon";

const INCIDENT_TYPES: { value: IncidentType; label: string }[] = [
  { value: "LANDSLIDE", label: "Landslide" },
  { value: "ROCKFALL", label: "Rockfall" },
  { value: "CRACK", label: "Crack" },
  { value: "ROAD_BLOCKAGE", label: "Road blockage" },
  { value: "SLOPE_MOVEMENT", label: "Slope movement" },
  { value: "FLOOD", label: "Flood" },
  { value: "OTHER", label: "Other" },
];

const SEVERITIES: RiskLevel[] = ["LOW", "MODERATE", "HIGH", "CRITICAL"];
const REPORTERS: { value: ReporterType; label: string }[] = [
  { value: "CITIZEN", label: "Citizen" },
  { value: "FIELD_OFFICER", label: "Field officer" },
  { value: "AUTHORITY", label: "Authority" },
];

export function FieldReportForm({ onSubmitted }: { onSubmitted: (r: IncidentReport) => void }) {
  const app = useApp();
  const [incidentType, setIncidentType] = useState<IncidentType>("LANDSLIDE");
  const [description, setDescription] = useState("");
  const [districtId, setDistrictId] = useState(app.districtId !== "ALL" ? app.districtId : DISTRICTS[0].id);
  const [roadOrVillage, setRoadOrVillage] = useState("");
  const [severity, setSeverity] = useState<RiskLevel>("MODERATE");
  const [reporterType, setReporterType] = useState<ReporterType>("FIELD_OFFICER");
  const [reporterName, setReporterName] = useState("");
  const [media, setMedia] = useState<MediaAttachment[]>([]);
  // Stable per-browser identifier, so a resumed queue keeps the same client keys.
  const [deviceId] = useState(() => {
    const existing = localStorage.getItem("ner-ews.device-id");
    if (existing) return existing;
    const generated = `dev-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem("ner-ews.device-id", generated);
    return generated;
  });
  const [location, setLocation] = useState<LatLng | null>(null);
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  const district = districtById(districtId);
  const valid = description.trim().length >= 10 && roadOrVillage.trim().length > 0;

  const captureLocation = () => {
    setLocError(null);
    if (!("geolocation" in navigator)) {
      setLocError("Geolocation is not available on this device. Enter the road or village instead.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocating(false);
      },
      () => {
        // Fall back to the district centroid so a report is never blocked by a denied permission.
        setLocation(district?.center ?? null);
        setLocError("Precise location unavailable — using the district centroid. Confirm the road or village.");
        setLocating(false);
      },
      { timeout: 8000, enableHighAccuracy: true },
    );
  };

  const submit = async (mode: "SUBMIT" | "OFFLINE") => {
    setTouched(true);
    if (!valid) {
      app.toast({ tone: "warning", title: "Report incomplete", body: "Add a description and the road or village." });
      return;
    }
    setBusy(true);
    // A stable client key generated before the first attempt. This is what makes an
    // offline queue safe to replay: the device can resend without knowing whether the
    // earlier attempt landed, and the server returns the original record rather than
    // creating a second incident for the same landslide.
    const point = location ?? district?.center;
    const draft: incidentService.FieldReportDraft = {
      incidentType,
      description: description.trim(),
      districtId,
      roadOrVillage: roadOrVillage.trim(),
      lat: point?.lat ?? 0,
      lng: point?.lng ?? 0,
      severity,
      reporterType,
      reporterName: reporterName.trim() || "Anonymous",
      clientId: `${deviceId}-${Date.now().toString(36)}`,
      deviceId,
      files: media.map((m) => m.file).filter(Boolean) as File[],
    };

    try {
      if (mode === "OFFLINE") {
        incidentService.queueOffline(draft);
        onSubmitted({
          ...draft,
          id: draft.clientId,
          district: district?.name ?? "",
          stateCode: district?.stateCode ?? "AS",
          location: point,
          severity: draft.severity as never,
          reporterType: draft.reporterType as never,
          incidentType: draft.incidentType as never,
          reportedAt: new Date().toISOString(),
          media: [],
          syncStatus: "PENDING_SYNC",
          verification: "PENDING",
        });
        app.toast({
          tone: "warning",
          title: "Saved on this device",
          body: "It will upload automatically when the connection returns.",
        });
        setDescription("");
        setRoadOrVillage("");
        setMedia([]);
        setLocation(null);
        setTouched(false);
        return;
      }
      const res = await incidentService.submitFieldReport(draft);
      onSubmitted(res.data);
      app.pushNotification({
        category: "CITIZEN_REPORT",
        title: `New ${incidentType.replace(/_/g, " ").toLowerCase()} report`,
        body: `${district?.name ?? ""} · ${roadOrVillage.trim()} — awaiting verification.`,
        href: "/field-reports",
      });
      app.toast({
        tone: "success",
        title: `Report submitted · ${res.data.id}`,
        body: "Sent to the district control room for verification.",
      });
      setDescription("");
      setRoadOrVillage("");
      setMedia([]);
      setLocation(null);
      setTouched(false);
    } catch (err) {
      // Never lose a field report to a bad link. If the upload fails it goes into the
      // device queue and is retried on reconnect, and the officer is told that
      // clearly rather than being asked to type it again.
      incidentService.queueOffline(draft);
      app.toast({
        tone: "warning",
        title: "No connection — saved on this device",
        body:
          err instanceof Error && err.message
            ? `${err.message} The report will upload automatically when the link returns.`
            : "The report will upload automatically when the link returns.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        void submit("SUBMIT");
      }}
      noValidate
    >
      <div className="grid grid-2 grid-1-mobile">
        <label className="field">
          Incident type
          <select value={incidentType} onChange={(e) => setIncidentType(e.target.value as IncidentType)}>
            {INCIDENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          Severity as observed
          <select value={severity} onChange={(e) => setSeverity(e.target.value as RiskLevel)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="field">
        Description
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What did you see? Include size, movement, and whether traffic or homes are affected."
          aria-describedby="desc-help"
          required
        />
      </label>
      <div
        id="desc-help"
        className="tiny"
        style={{ marginTop: -8, color: touched && description.trim().length < 10 ? "var(--sev)" : "var(--ink-3)" }}
      >
        {touched && description.trim().length < 10
          ? "Please describe the incident in at least a few words."
          : "At least 10 characters."}
      </div>

      <div className="grid grid-2 grid-1-mobile">
        <label className="field">
          District
          <select value={districtId} onChange={(e) => setDistrictId(e.target.value)}>
            {DISTRICTS.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.stateCode})
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          Road / village
          <input
            type="text"
            value={roadOrVillage}
            onChange={(e) => setRoadOrVillage(e.target.value)}
            placeholder="e.g. NH-27, km 42 or Mahur village"
            style={{ borderColor: touched && !roadOrVillage.trim() ? "var(--sev)" : undefined }}
            required
          />
        </label>
      </div>

      <div className="grid grid-2 grid-1-mobile">
        <label className="field">
          Reporter type
          <select value={reporterType} onChange={(e) => setReporterType(e.target.value as ReporterType)}>
            {REPORTERS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Name or unit (optional)
          <input
            type="text"
            value={reporterName}
            onChange={(e) => setReporterName(e.target.value)}
            placeholder="e.g. PWD Field Unit 3"
          />
        </label>
      </div>

      <div>
        <div className="eyebrow" style={{ marginBottom: 5 }}>
          Photos / video
        </div>
        <FileUploader media={media} onChange={setMedia} />
      </div>

      <div className="card soft" style={{ padding: "10px 12px" }}>
        <div className="row between">
          <div>
            <div className="eyebrow">GPS location</div>
            <div className="mono" style={{ fontSize: 13 }}>
              {location ? `${location.lat.toFixed(5)}, ${location.lng.toFixed(5)}` : "Not captured"}
            </div>
          </div>
          <button className="btn sm" type="button" onClick={captureLocation} disabled={locating}>
            <IconPin size={14} /> {locating ? "Locating…" : location ? "Update" : "Use my location"}
          </button>
        </div>
        {locError && (
          <div className="tiny" style={{ color: "var(--mod)", marginTop: 6 }}>
            {locError}
          </div>
        )}
        {location && (
          <div
            style={{
              marginTop: 8,
              height: 74,
              borderRadius: "var(--r-sm)",
              border: "1px solid var(--line)",
              background:
                "repeating-linear-gradient(45deg, #eef1ea 0 8px, #e7ebe4 8px 16px)",
              position: "relative",
            }}
            aria-label="Location preview"
          >
            <span
              style={{
                position: "absolute",
                left: "50%",
                top: "50%",
                transform: "translate(-50%, -50%)",
                color: "var(--sev)",
              }}
            >
              <IconPin size={22} />
            </span>
            <span className="tiny mono" style={{ position: "absolute", left: 6, bottom: 4, color: "var(--ink-3)" }}>
              {district?.name}
            </span>
          </div>
        )}
      </div>

      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Submit report"}
        </button>
        <button className="btn" type="button" disabled={busy} onClick={() => void submit("OFFLINE")}>
          Save offline
        </button>
        <span className="tiny muted">
          Offline saves queue locally and sync when the connection returns.
        </span>
      </div>
    </form>
  );
}
