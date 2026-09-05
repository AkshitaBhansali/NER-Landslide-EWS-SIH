import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useApp, districtsInScope } from "@/state/AppContext";
import { STATES } from "@/data/regions";
import { useAsync } from "@/state/useAsync";
import { weatherService } from "@/services";
import { Drawer } from "@/components/ui/primitives";
import { relativeTime } from "@/utils";
import {
  IconAlert,
  IconBell,
  IconCamera,
  IconCheck,
  IconChevron,
  IconCloud,
  IconGlobe,
  IconHistory,
  IconMenu,
  IconMountain,
  IconOverview,
  IconPulse,
  IconRain,
  IconReport,
  IconSearch,
  IconSensor,
  IconSettings,
  IconSun,
  IconWifi,
  IconWifiOff,
} from "@/components/ui/Icon";

const NAV = [
  { to: "/", label: "Overview", icon: IconOverview, end: true },
  { to: "/live", label: "Live Monitoring", icon: IconPulse },
  { to: "/alerts", label: "Risk & Alerts", icon: IconAlert },
  { to: "/custom-alerts", label: "Custom Rules", icon: IconSettings },
  { to: "/gis", label: "GIS Intelligence", icon: IconGlobe },
  { to: "/sensors", label: "Sensor Network", icon: IconSensor },
  { to: "/field-reports", label: "Field Reports", icon: IconCamera },
  { to: "/incidents", label: "Incident History", icon: IconHistory },
  { to: "/reports", label: "Reports & Analytics", icon: IconReport },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

const MOBILE_NAV = [
  { to: "/", label: "Overview", icon: IconOverview, end: true },
  { to: "/alerts", label: "Alerts", icon: IconAlert },
  { to: "/gis", label: "GIS", icon: IconGlobe },
  { to: "/field-reports", label: "Report", icon: IconCamera },
  { to: "/sensors", label: "Sensors", icon: IconSensor },
];

export function DashboardLayout({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const location = useLocation();
  const app = useApp();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const criticalCount = app.notifications.filter(
    (n) => !n.read && n.category === "CRITICAL_ALERT",
  ).length;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <div
        className={`sidebar-backdrop${mobileOpen ? " show" : ""}`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />

      <nav
        className={`sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " open" : ""}`}
        aria-label="Primary"
      >
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            <IconMountain size={17} style={{ color: "#e8f2ef" }} />
          </span>
          {!collapsed && (
            <span className="brand-text">
              <strong>NER-Landslide EWS</strong>
              <span>Early Warning Platform</span>
            </span>
          )}
        </div>

        <div className="sidebar-nav">
          {!collapsed && <div className="nav-group-label">Operations</div>}
          {NAV.slice(0, 6).map((item) => (
            <NavItem key={item.to} item={item} collapsed={collapsed} count={item.to === "/alerts" ? criticalCount : 0} />
          ))}
          {!collapsed && <div className="nav-group-label">Intelligence</div>}
          {NAV.slice(6).map((item) => (
            <NavItem key={item.to} item={item} collapsed={collapsed} count={0} />
          ))}
        </div>

        <div className="sidebar-foot">
          <button
            className="sidebar-toggle"
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <IconChevron
              size={14}
              style={{ transform: collapsed ? "none" : "rotate(180deg)" }}
            />
            {!collapsed && <span style={{ fontSize: 11.5 }}>Collapse</span>}
          </button>
          {!collapsed && (
            <div style={{ marginTop: 8, lineHeight: 1.4 }}>
              MDoNER · SIH PS 26001
              <br />
              Research prototype · simulated telemetry
            </div>
          )}
        </div>
      </nav>

      <div className="app-main">
        <TopBar onMenu={() => setMobileOpen(true)} onBell={() => setNotifOpen(true)} />
        <main className="app-content" id="main">
          {children}
        </main>
      </div>

      <nav className="bottom-nav" aria-label="Primary mobile">
        {MOBILE_NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? "active" : "")}>
            <Icon size={17} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <NotificationDrawer open={notifOpen} onClose={() => setNotifOpen(false)} />
      <ToastStack />
    </div>
  );
}

function NavItem({
  item,
  collapsed,
  count,
}: {
  item: (typeof NAV)[number];
  collapsed: boolean;
  count: number;
}) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
      title={collapsed ? item.label : undefined}
    >
      <Icon size={17} />
      {!collapsed && <span>{item.label}</span>}
      {!collapsed && count > 0 && <span className="nav-count">{count}</span>}
    </NavLink>
  );
}

/* ------------------------------------------------------------------ topbar */

function TopBar({ onMenu, onBell }: { onMenu: () => void; onBell: () => void }) {
  const app = useApp();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const weather = useAsync(() => weatherService.getWeather(app.scope), [app.districtId, app.stateCode]);

  const criticalOpen = app.notifications.some((n) => !n.read && n.category === "CRITICAL_ALERT");

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    navigate(`/alerts?q=${encodeURIComponent(query.trim())}`);
    app.toast({ tone: "info", title: `Searching alerts for "${query.trim()}"` });
  };

  const w = weather.data;
  const WeatherIcon =
    w?.condition === "HEAVY_RAIN" || w?.condition === "THUNDERSTORM"
      ? IconRain
      : w?.condition === "LIGHT_RAIN" || w?.condition === "CLOUDY"
        ? IconCloud
        : IconSun;

  return (
    <header className="topbar noprint">
      <button className="icon-btn" type="button" onClick={onMenu} aria-label="Open navigation" style={{ display: "none" }} id="menu-btn">
        <IconMenu size={17} />
      </button>
      <style>{`@media (max-width: 960px){ #menu-btn{ display:grid !important; } }`}</style>

      <RegionSelector />

      <form className="search-box" role="search" onSubmit={onSearch}>
        <IconSearch />
        <input
          type="search"
          placeholder="Search zones, roads, alerts…"
          aria-label="Search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>

      <div className="topbar-spacer" />

      {w && (
        <span className="topbar-chip" title={`Rainfall 24h: ${w.rainfall24h} mm · threshold ${w.alertThreshold24h} mm`}>
          <WeatherIcon size={15} />
          <span className="mono">{w.temperature}°C</span>
          <span className="muted">·</span>
          <span className="mono">{w.rainfall24h} mm/24h</span>
        </span>
      )}

      <span
        className="topbar-chip"
        title={app.connection === "ONLINE" ? "Connected to platform services" : "Working offline — reports will queue"}
      >
        {app.connection === "ONLINE" ? (
          <IconWifi size={14} style={{ color: "var(--low)" }} />
        ) : (
          <IconWifiOff size={14} style={{ color: "var(--sev)" }} />
        )}
        {app.connection === "ONLINE" ? "Connected" : "Offline"}
      </span>

      <span
        className="topbar-chip"
        title="Sensor telemetry on this platform is produced by a physics-informed simulator, not by field hardware."
      >
        Sensor stream · Simulated
      </span>

      <span
        className="topbar-chip"
        style={
          criticalOpen
            ? { background: "var(--sev-bg)", borderColor: "var(--sev)", color: "#7d201c", fontWeight: 600 }
            : { background: "var(--low-bg)", borderColor: "#bcd9b4", color: "#2f6330" }
        }
        title="Region-wide emergency status"
      >
        {criticalOpen ? "⚠ Emergency active" : "✓ No emergency"}
      </span>

      <button className="icon-btn" type="button" onClick={onBell} aria-label={`Notifications, ${app.unreadCount} unread`}>
        <IconBell size={17} />
        {app.unreadCount > 0 && <span className="dot-count">{app.unreadCount}</span>}
      </button>

      <button
        className="user-chip"
        type="button"
        onClick={() => app.toast({ tone: "info", title: "Profile", body: "Authentication is owned by the backend workstream." })}
      >
        <span className="avatar" aria-hidden="true">
          DC
        </span>
        <span style={{ fontSize: 12, textAlign: "left", lineHeight: 1.2 }}>
          District Control
          <br />
          <span className="muted tiny">Duty officer</span>
        </span>
      </button>
    </header>
  );
}

/* ------------------------------------------------------------------ region selector */

export function RegionSelector() {
  const app = useApp();
  const districts = districtsInScope(app.stateCode);

  return (
    <div className="row" style={{ gap: 6 }}>
      <select
        value={app.stateCode}
        onChange={(e) => app.setStateCode(e.target.value)}
        aria-label="Select state"
        style={{ maxWidth: 180 }}
      >
        <option value="ALL">All NER states</option>
        {STATES.map((s) => (
          <option key={s.code} value={s.code}>
            {s.name}
          </option>
        ))}
      </select>
      <select
        value={app.districtId}
        onChange={(e) => app.setDistrictId(e.target.value)}
        aria-label="Select district"
        style={{ maxWidth: 190 }}
      >
        <option value="ALL">All districts</option>
        {districts.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ------------------------------------------------------------------ notifications */

const NOTIF_STYLE: Record<string, { bg: string; fg: string; icon: string }> = {
  CRITICAL_ALERT: { bg: "var(--sev-bg)", fg: "var(--sev)", icon: "▲" },
  HIGH_RISK: { bg: "var(--high-bg)", fg: "var(--high)", icon: "▲" },
  SENSOR_FAILURE: { bg: "var(--mod-bg)", fg: "var(--mod)", icon: "◆" },
  ROAD_BLOCKAGE: { bg: "var(--high-bg)", fg: "var(--high)", icon: "≡" },
  CITIZEN_REPORT: { bg: "var(--info-bg)", fg: "var(--info)", icon: "✎" },
  SYSTEM: { bg: "var(--surface-2)", fg: "var(--ink-3)", icon: "•" },
};

function NotificationDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const app = useApp();
  const navigate = useNavigate();

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Notifications"
      subtitle={`${app.unreadCount} unread · ${app.notifications.length} total`}
      labelledBy="notif-title"
      footer={
        <button className="btn sm" type="button" onClick={app.markAllRead}>
          <IconCheck size={13} /> Mark all read
        </button>
      }
    >
      {app.notifications.length === 0 ? (
        <div className="state-block">
          <strong>No notifications</strong>
          <span>Alerts and system messages will appear here.</span>
        </div>
      ) : (
        <div style={{ margin: "-14px -16px" }}>
          {app.notifications.map((n) => {
            const style = NOTIF_STYLE[n.category] ?? NOTIF_STYLE.SYSTEM;
            return (
              <button
                key={n.id}
                type="button"
                className={`notif-item${n.read ? "" : " unread"}`}
                onClick={() => {
                  app.markRead(n.id);
                  if (n.href) {
                    navigate(n.href);
                    onClose();
                  }
                }}
              >
                <span className="ni-icon" style={{ background: style.bg, color: style.fg }} aria-hidden="true">
                  {style.icon}
                </span>
                <span style={{ minWidth: 0 }}>
                  <h4>{n.title}</h4>
                  <p>{n.body}</p>
                  <span className="tiny muted mono">{relativeTime(n.createdAt)}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </Drawer>
  );
}

/* ------------------------------------------------------------------ toasts */

function ToastStack() {
  const app = useApp();
  if (!app.toasts.length) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {app.toasts.map((t) => (
        <div key={t.id} className={`toast ${t.tone}`}>
          <span style={{ minWidth: 0 }}>
            <strong style={{ fontSize: 12.5 }}>{t.title}</strong>
            {t.body && <div className="t-body">{t.body}</div>}
          </span>
          <button type="button" onClick={() => app.dismissToast(t.id)} aria-label="Dismiss">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
