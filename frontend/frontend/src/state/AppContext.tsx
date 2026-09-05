import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AppNotification, ConnectionState, ToastMessage } from "@/types";
import { DISTRICTS, districtById, STATES } from "@/data/regions";
import { systemService } from "@/services";
import { uid } from "@/utils";

/**
 * Only genuinely cross-cutting state lives here: the region/district scope every page
 * filters by, the notification feed, transient toasts and the connection indicator.
 * Page-local concerns (filters, sort, drawers) stay in the pages that own them.
 */

export interface AppState {
  stateCode: string; // "ALL" or a StateCode
  districtId: string; // "ALL" or a district id
  stateName: string;
  districtName: string;
  scopeLabel: string;
  /** Scope object accepted by every service. */
  scope: { stateCode: string; districtId: string };
  setStateCode: (code: string) => void;
  setDistrictId: (id: string) => void;

  connection: ConnectionState;
  setConnection: (c: ConnectionState) => void;

  notifications: AppNotification[];
  unreadCount: number;
  markAllRead: () => void;
  markRead: (id: string) => void;
  pushNotification: (n: Omit<AppNotification, "id" | "createdAt" | "read">) => void;

  toasts: ToastMessage[];
  toast: (t: Omit<ToastMessage, "id">) => void;
  dismissToast: (id: string) => void;

  /** Ticks every 30s so "last updated" labels stay honest without refetching. */
  clockTick: number;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [stateCode, setStateCodeRaw] = useState<string>("ALL");
  const [districtId, setDistrictId] = useState<string>("ALL");
  const [connection, setConnection] = useState<ConnectionState>("ONLINE");
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [clockTick, setClockTick] = useState(0);

  useEffect(() => {
    const t = window.setInterval(() => setClockTick((n) => n + 1), 30000);
    return () => window.clearInterval(t);
  }, []);

  // Notifications come from the backend and refresh on the same 30s tick. A failure
  // here is not worth a toast: the feed is secondary, and the connection indicator
  // already tells the operator the link is down.
  useEffect(() => {
    let cancelled = false;
    systemService
      .getNotifications()
      .then((res) => {
        if (!cancelled) setNotifications(res.data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [clockTick]);

  // Browser connectivity feeds the top-bar indicator; the offline-sync layer will
  // eventually own this signal.
  useEffect(() => {
    const online = () => setConnection("ONLINE");
    const offline = () => setConnection("OFFLINE");
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    if (!navigator.onLine) setConnection("OFFLINE");
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  const setStateCode = useCallback((code: string) => {
    setStateCodeRaw(code);
    setDistrictId("ALL"); // district must always belong to the selected state
  }, []);

  const toast = useCallback((t: Omit<ToastMessage, "id">) => {
    const id = uid("toast");
    setToasts((prev) => [...prev, { ...t, id }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 4500);
  }, []);

  const dismissToast = useCallback(
    (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)),
    [],
  );

  const pushNotification = useCallback((n: Omit<AppNotification, "id" | "createdAt" | "read">) => {
    setNotifications((prev) => [
      { ...n, id: uid("n"), createdAt: new Date().toISOString(), read: false },
      ...prev,
    ]);
  }, []);

  const markAllRead = useCallback(
    () => setNotifications((prev) => prev.map((n) => ({ ...n, read: true }))),
    [],
  );
  const markRead = useCallback(
    (id: string) => setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n))),
    [],
  );

  const value = useMemo<AppState>(() => {
    const stateName = stateCode === "ALL" ? "All NER states" : STATES.find((s) => s.code === stateCode)?.name ?? stateCode;
    const districtName = districtId === "ALL" ? "All districts" : districtById(districtId)?.name ?? districtId;
    const scopeLabel = districtId !== "ALL" ? `${districtName}, ${stateName}` : stateName;
    return {
      stateCode,
      districtId,
      stateName,
      districtName,
      scopeLabel,
      scope: { stateCode, districtId },
      setStateCode,
      setDistrictId,
      connection,
      setConnection,
      notifications,
      unreadCount: notifications.filter((n) => !n.read).length,
      markAllRead,
      markRead,
      pushNotification,
      toasts,
      toast,
      dismissToast,
      clockTick,
    };
  }, [
    stateCode,
    districtId,
    connection,
    notifications,
    toasts,
    clockTick,
    setStateCode,
    markAllRead,
    markRead,
    pushNotification,
    toast,
    dismissToast,
  ]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>");
  return ctx;
}

export const districtsInScope = (stateCode: string) =>
  stateCode === "ALL" ? DISTRICTS : DISTRICTS.filter((d) => d.stateCode === stateCode);
