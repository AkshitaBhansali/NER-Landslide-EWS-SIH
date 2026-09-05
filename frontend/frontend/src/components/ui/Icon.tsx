import type { SVGProps } from "react";

/** Minimal stroke icon set — no icon dependency, so the bundle stays offline-friendly. */

type P = SVGProps<SVGSVGElement> & { size?: number };

const Base = ({ size = 16, children, ...rest }: P) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.8}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    {...rest}
  >
    {children}
  </svg>
);

export const IconOverview = (p: P) => (
  <Base {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1" />
    <rect x="14" y="3" width="7" height="5" rx="1" />
    <rect x="14" y="12" width="7" height="9" rx="1" />
    <rect x="3" y="16" width="7" height="5" rx="1" />
  </Base>
);

export const IconPulse = (p: P) => (
  <Base {...p}>
    <path d="M2 12h4l2.5-7 4 14L15 12h7" />
  </Base>
);

export const IconAlert = (p: P) => (
  <Base {...p}>
    <path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </Base>
);

export const IconGlobe = (p: P) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z" />
  </Base>
);

export const IconSensor = (p: P) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="2.5" />
    <path d="M7.5 16.5a6 6 0 0 1 0-9M16.5 7.5a6 6 0 0 1 0 9M4.5 19.5a10 10 0 0 1 0-15M19.5 4.5a10 10 0 0 1 0 15" />
  </Base>
);

export const IconCamera = (p: P) => (
  <Base {...p}>
    <path d="M3 8a2 2 0 0 1 2-2h2.5l1.2-2h6.6L16.5 6H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    <circle cx="12" cy="12.5" r="3.2" />
  </Base>
);

export const IconHistory = (p: P) => (
  <Base {...p}>
    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
    <path d="M3 4v4h4M12 7v5l3.5 2" />
  </Base>
);

export const IconReport = (p: P) => (
  <Base {...p}>
    <path d="M6 3h8l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
    <path d="M14 3v5h5M9 13v4M12 11v6M15 15v2" />
  </Base>
);

export const IconSettings = (p: P) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
  </Base>
);

export const IconBell = (p: P) => (
  <Base {...p}>
    <path d="M18 8a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7Z" />
    <path d="M10.3 20a2 2 0 0 0 3.4 0" />
  </Base>
);

export const IconSearch = (p: P) => (
  <Base {...p} size={p.size ?? 14}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Base>
);

export const IconMenu = (p: P) => (
  <Base {...p}>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </Base>
);

export const IconClose = (p: P) => (
  <Base {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Base>
);

export const IconChevron = (p: P) => (
  <Base {...p}>
    <path d="m9 6 6 6-6 6" />
  </Base>
);

export const IconRain = (p: P) => (
  <Base {...p}>
    <path d="M7 15a4.5 4.5 0 0 1 .6-9 6 6 0 0 1 11.3 2.1A3.7 3.7 0 0 1 18.5 15Z" />
    <path d="M8 18l-1 3M12.5 18l-1 3M17 18l-1 3" />
  </Base>
);

export const IconCloud = (p: P) => (
  <Base {...p}>
    <path d="M7 18a4.5 4.5 0 0 1 .6-9 6 6 0 0 1 11.3 2.1A3.7 3.7 0 0 1 18.5 18Z" />
  </Base>
);

export const IconSun = (p: P) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Base>
);

export const IconRoad = (p: P) => (
  <Base {...p}>
    <path d="M6 3 3 21M18 3l3 18M12 4v3M12 10.5v3M12 17v3" />
  </Base>
);

export const IconWifiOff = (p: P) => (
  <Base {...p}>
    <path d="M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 3-2M19 13a10 10 0 0 0-7-2.9M2 8.8A15 15 0 0 1 6 6.3M22 8.8a15 15 0 0 0-6-3.3M12 20h.01" />
  </Base>
);

export const IconWifi = (p: P) => (
  <Base {...p}>
    <path d="M5 13a10 10 0 0 1 14 0M2 8.8a15 15 0 0 1 20 0M8.5 16.5a5 5 0 0 1 7 0M12 20h.01" />
  </Base>
);

export const IconDownload = (p: P) => (
  <Base {...p}>
    <path d="M12 3v12M7 11l5 5 5-5M4 20h16" />
  </Base>
);

export const IconPrint = (p: P) => (
  <Base {...p}>
    <path d="M7 8V3h10v5" />
    <rect x="4" y="8" width="16" height="8" rx="1.5" />
    <path d="M7 14h10v7H7z" />
  </Base>
);

export const IconRefresh = (p: P) => (
  <Base {...p}>
    <path d="M20 11a8 8 0 1 0-1.5 5.5" />
    <path d="M20 5v6h-6" />
  </Base>
);

export const IconLayers = (p: P) => (
  <Base {...p}>
    <path d="m12 3 9 5-9 5-9-5 9-5Z" />
    <path d="m3 13 9 5 9-5M3 17l9 5 9-5" />
  </Base>
);

export const IconPin = (p: P) => (
  <Base {...p}>
    <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z" />
    <circle cx="12" cy="10" r="2.6" />
  </Base>
);

export const IconCheck = (p: P) => (
  <Base {...p}>
    <path d="m4 12.5 5 5L20 6.5" />
  </Base>
);

export const IconMountain = (p: P) => (
  <Base {...p}>
    <path d="m3 20 6.5-12 4 7 2.5-4L21 20Z" />
  </Base>
);
