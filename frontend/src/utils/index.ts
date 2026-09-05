import type { AlertSeverity, RiskLevel } from "@/types";

/* ------------------------------------------------------------------ deterministic randomness */

/** Deterministic PRNG, so derived visual values are stable across reloads. */
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return function next(): number {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export const rngFor = (key: string) => mulberry32(hashString(key));

export const pick = <T,>(rand: () => number, items: readonly T[]): T =>
  items[Math.floor(rand() * items.length) % items.length];

export const between = (rand: () => number, min: number, max: number) => min + rand() * (max - min);

export const round = (n: number, dp = 1) => Number(n.toFixed(dp));

export const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));

/* ------------------------------------------------------------------ risk semantics */

/** Single source of truth for the score -> level mapping used across every module. */
export function riskLevelFromScore(score: number): RiskLevel {
  if (score >= 80) return "CRITICAL";
  if (score >= 60) return "HIGH";
  if (score >= 35) return "MODERATE";
  return "LOW";
}

export const RISK_ORDER: Record<RiskLevel, number> = {
  LOW: 0,
  MODERATE: 1,
  HIGH: 2,
  CRITICAL: 3,
};

export const SEVERITY_ORDER: Record<AlertSeverity, number> = {
  INFORMATION: 0,
  MODERATE: 1,
  HIGH: 2,
  CRITICAL: 3,
};

export const riskVar = (level: RiskLevel | AlertSeverity): string => {
  switch (level) {
    case "CRITICAL":
      return "var(--sev)";
    case "HIGH":
      return "var(--high)";
    case "MODERATE":
      return "var(--mod)";
    case "INFORMATION":
      return "var(--ink-3)";
    default:
      return "var(--low)";
  }
};

export const riskBgVar = (level: RiskLevel | AlertSeverity): string => {
  switch (level) {
    case "CRITICAL":
      return "var(--sev-bg)";
    case "HIGH":
      return "var(--high-bg)";
    case "MODERATE":
      return "var(--mod-bg)";
    case "INFORMATION":
      return "var(--surface-2)";
    default:
      return "var(--low-bg)";
  }
};

/** Risk is never signalled by colour alone — every badge carries this glyph too. */
export const riskGlyph = (level: RiskLevel | AlertSeverity): string => {
  switch (level) {
    case "CRITICAL":
      return "▲▲";
    case "HIGH":
      return "▲";
    case "MODERATE":
      return "◆";
    case "INFORMATION":
      return "•";
    default:
      return "●";
  }
};

export const severityToRisk = (s: AlertSeverity): RiskLevel =>
  s === "INFORMATION" ? "LOW" : (s as RiskLevel);

/* ------------------------------------------------------------------ formatting */

export const titleCase = (s: string) =>
  s
    .toLowerCase()
    .split(/[\s_]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function relativeTime(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Math.round((now - then) / 1000);
  if (diff < 60) return `${Math.max(diff, 0)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export const compactNumber = (n: number): string => {
  if (n >= 1e7) return `${(n / 1e7).toFixed(1)} Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(1)} L`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n));
};

export const formatBytes = (b: number): string => {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
};

export const isoDaysAgo = (days: number, base = Date.now()): string =>
  new Date(base - days * 86400000).toISOString();

export const isoMinutesAgo = (minutes: number, base = Date.now()): string =>
  new Date(base - minutes * 60000).toISOString();

/* ------------------------------------------------------------------ misc */

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const uid = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

export function sortBy<T>(items: T[], key: (t: T) => number | string, dir: "asc" | "desc" = "asc") {
  return [...items].sort((a, b) => {
    const av = key(a);
    const bv = key(b);
    if (av === bv) return 0;
    const cmp = av > bv ? 1 : -1;
    return dir === "asc" ? cmp : -cmp;
  });
}

export const matchesQuery = (query: string, ...fields: (string | undefined)[]) => {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return fields.some((f) => (f ?? "").toLowerCase().includes(q));
};
