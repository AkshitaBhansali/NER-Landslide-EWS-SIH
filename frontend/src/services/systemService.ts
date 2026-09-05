import type { AppNotification, ServiceResult, SystemStatus } from "@/types";
import * as A from "./adapters";
import { get, post } from "./api";

type Raw = Record<string, unknown>;

/** GET /api/system/status */
export const getSystemStatus = async (): Promise<ServiceResult<SystemStatus>> => {
  const res = await get<Raw>("/system/status");
  const services = (res.data.services as Raw[]) ?? [];
  const up = services.filter((s) => s.status === "OPERATIONAL").length;
  return {
    ...res,
    data: {
      connection:
        res.data.status === "OPERATIONAL"
          ? "ONLINE"
          : res.data.status === "DEGRADED"
            ? "DEGRADED"
            : "OFFLINE",
      ingestLagSeconds: 0,
      modelLastRunAt: String(
        services.find((s) => s.name === "Risk engine")?.last_run ?? new Date().toISOString(),
      ),
      servicesUp: up,
      servicesTotal: services.length,
      services: services.map((s) => ({
        name: String(s.name),
        status: String(s.status),
        detail: s.detail == null ? undefined : String(s.detail),
      })),
      dataConfidence: String(res.data.data_confidence ?? "SYNTHETIC"),
    },
  };
};

export const getDistricts = async () => {
  const res = await get<Raw[]>("/districts");
  return { ...res, data: res.data.map(A.adaptDistrict) };
};

export const getNotifications = async (): Promise<ServiceResult<AppNotification[]>> => {
  const res = await get<Raw[]>("/notifications");
  return { ...res, data: res.data.map(A.adaptNotification) };
};

export const markNotificationRead = (id: string) =>
  post<Raw>(`/notifications/${encodeURIComponent(id)}/read`);

export const markAllNotificationsRead = () => post<Raw>("/notifications/read-all");

export const getThresholds = () => get<Raw[]>("/settings/thresholds");

export const setDistrictThreshold = (districtId: string, value: number) =>
  post<Raw>(`/settings/thresholds/${encodeURIComponent(districtId)}`, {
    alert_threshold_24h: value,
  });

export const getSyncStatus = () => get<Raw>("/sync/status");
