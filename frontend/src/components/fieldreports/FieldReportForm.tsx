import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { IncidentReport, IncidentType, LatLng, MediaAttachment, ReporterType, RiskLevel } from "@/types";
import { DISTRICTS, districtById } from "@/data/regions";
import { incidentService } from "@/services";
import { useApp } from "@/state/AppContext";
import { FileUploader } from "./FileUploader";
import { IconPin } from "@/components/ui/Icon";

function LocationPreviewMap({ lat, lng, label }: { lat: number; lng: number; label?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    if (!mapRef.current) {
      const map = L.map(containerRef.current, {
        center: [lat, lng],
        zoom: 13,
        zoomControl: false,
        attributionControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        touchZoom: false,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
      }).addTo(map);

      const customIcon = L.divIcon({
        className: "custom-map-pin",
        html: `<div style="
          width: 26px;
          height: 26px;
          border-radius: 50%;
          background: #b5342e;
          border: 3px solid #ffffff;
          box-shadow: 0 2px 6px rgba(0,0,0,0.35);
          display: flex;
          align-items: center;
          justify-content: center;
        ">
          <div style="width: 7px; height: 7px; border-radius: 50%; background: #ffffff;"></div>
        </div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13],
      });

      const marker = L.marker([lat, lng], { icon: customIcon }).addTo(map);
      mapRef.current = map;
      markerRef.current = marker;

      setTimeout(() => {
        map.invalidateSize();
      }, 150);
    } else {
      mapRef.current.setView([lat, lng], 13);
      if (markerRef.current) {
        markerRef.current.setLatLng([lat, lng]);
      }
      mapRef.current.invalidateSize();
    }
  }, [lat, lng]);

  useEffect(() => {
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []);

  return (
    <div
      style={{
        marginTop: 8,
        height: 130,
        borderRadius: "var(--r-sm)",
        border: "1px solid var(--line)",
        overflow: "hidden",
        position: "relative",
      }}
      aria-label="Location preview map"
    >
      <div ref={containerRef} style={{ width: "100%", height: "100%", zIndex: 1 }} />
      {label && (
        <span
          className="tiny mono"
          style={{
            position: "absolute",
            left: 8,
            bottom: 6,
            zIndex: 1000,
            background: "rgba(255, 255, 255, 0.92)",
            padding: "3px 7px",
            borderRadius: 4,
            border: "1px solid rgba(0, 0, 0, 0.12)",
            boxShadow: "0 1px 4px rgba(0,0,0,0.15)",
            color: "var(--ink)",
            fontWeight: 600,
          }}
        >
          {label}
        </span>
      )}
    </div>
  );
}

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
  const [locationLabel, setLocationLabel] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  const district = districtById(districtId);
  const valid = description.trim().length >= 10 && roadOrVillage.trim().length > 0;

  const captureLocation = async () => {
    setLocError(null);
    setLocating(true);

    const applyLocation = (lat: number, lng: number, label?: string) => {
      setLocation({ lat, lng });
      setLocError(null);
      setLocating(false);

      // Auto-select nearest district in system dataset
      let nearest = DISTRICTS[0];
      let minDistance = Infinity;
      for (const d of DISTRICTS) {
        const dist = Math.hypot(d.center.lat - lat, d.center.lng - lng);
        if (dist < minDistance) {
          minDistance = dist;
          nearest = d;
        }
      }
      if (nearest) {
        setDistrictId(nearest.id);
      }

      const displayLabel = label || nearest?.name || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      setLocationLabel(displayLabel);

      app.toast({
        tone: "success",
        title: "Location captured",
        body: `${displayLabel} (${lat.toFixed(5)}, ${lng.toFixed(5)})`,
      });
    };

    const fallbackToIpOrDistrict = async () => {
      // 1. Try ipapi.co
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 3500);
        const res = await fetch("https://ipapi.co/json/", { signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) {
          const data = (await res.json()) as { latitude?: number; longitude?: number; city?: string; region?: string };
          if (typeof data.latitude === "number" && typeof data.longitude === "number") {
            const label = data.city ? `${data.city}${data.region ? `, ${data.region}` : ""}` : undefined;
            applyLocation(data.latitude, data.longitude, label);
            return;
          }
        }
      } catch {
        // fallback
      }

      // 2. Try geojs.io
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 3500);
        const res = await fetch("https://get.geojs.io/v1/ip/geo.json", { signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) {
          const data = (await res.json()) as { latitude?: string | number; longitude?: string | number; city?: string; region?: string };
          const lat = typeof data.latitude === "string" ? parseFloat(data.latitude) : data.latitude;
          const lng = typeof data.longitude === "string" ? parseFloat(data.longitude) : data.longitude;
          if (typeof lat === "number" && !isNaN(lat) && typeof lng === "number" && !isNaN(lng)) {
            const label = data.city ? `${data.city}${data.region ? `, ${data.region}` : ""}` : undefined;
            applyLocation(lat, lng, label);
            return;
          }
        }
      } catch {
        // fallback
      }

      // 3. Try freeipapi.com
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 3500);
        const res = await fetch("https://freeipapi.com/api/json", { signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) {
          const data = (await res.json()) as { latitude?: number; longitude?: number; cityName?: string; regionName?: string };
          if (typeof data.latitude === "number" && typeof data.longitude === "number") {
            const label = data.cityName ? `${data.cityName}${data.regionName ? `, ${data.regionName}` : ""}` : undefined;
            applyLocation(data.latitude, data.longitude, label);
            return;
          }
        }
      } catch {
        // fallback
      }

      const center = district?.center ?? { lat: 25.57, lng: 91.88 };
      applyLocation(center.lat, center.lng);
    };

    if (!("geolocation" in navigator)) {
      await fallbackToIpOrDistrict();
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        applyLocation(pos.coords.latitude, pos.coords.longitude);
      },
      () => {
        void fallbackToIpOrDistrict();
      },
      { timeout: 4000, enableHighAccuracy: true, maximumAge: 30000 },
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
          <LocationPreviewMap lat={location.lat} lng={location.lng} label={locationLabel || district?.name} />
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
