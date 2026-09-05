"""Quarterly report renderer.

Turns the `/api/reports/quarterly` payload into a printable HTML document in the
visual language of a government intelligence report: paper stock, serif headings,
monospace labels, hairline rules, and figures that sit still.

Three decisions worth stating:

1. **Charts are server-rendered inline SVG, not a charting library.** The target
   reader is a district office that may be on a satellite link or none at all, and
   a report whose charts are blank rectangles because a CDN was unreachable is not
   a report. Everything here renders from the file itself with no network and no
   JavaScript.

2. **There is no recommendations section.** The report states what happened, what
   the instruments recorded, and how the model performed. What to do about it is
   the district administration's decision, and an auto-generated action list under
   a government letterhead invites a deference it has not earned.

3. **Provenance is printed, not disclaimed.** Each page footer carries the
   provenance chips for the data on it — Historical, Simulated, Model-derived,
   User-reported. That is more honest than a banner nobody reads, and it survives
   being photocopied.
"""
from __future__ import annotations

import html
import math
from datetime import datetime

# --------------------------------------------------------------------------- #
# Palette — the sample report's tokens
# --------------------------------------------------------------------------- #
CSS = """
:root{
  --ink:#16211f; --ink-2:#3f504c; --ink-3:#6b7b77;
  --paper:#f7f5ef; --card:#ffffff; --line:#e2ded2; --line-2:#cfcabb;
  --geo:#0f5a52; --geo-soft:#e2efec;
  --low:#4a9d4a; --mod:#e6a52a; --high:#d1642e; --sev:#b5342e;
  --low-bg:#eaf3e2; --mod-bg:#fbf0d8; --high-bg:#f8e6da; --sev-bg:#f6e0dd;
}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:var(--paper);color:var(--ink);
     font-family:"Inter","Segoe UI",system-ui,sans-serif;font-size:15px;line-height:1.65}
.page{width:210mm;min-height:296mm;margin:16px auto;background:var(--card);
      padding:22mm 20mm 20mm;position:relative;box-shadow:0 2px 24px rgba(22,33,31,.10);
      border:1px solid var(--line)}
@media print{body{background:#fff}
  .page{box-shadow:none;border:none;margin:0;width:auto;min-height:auto;page-break-after:always}
  .noprint{display:none!important}}
h1,h2,h3,h4{font-family:Georgia,"Times New Roman",serif;font-weight:500;color:var(--ink);margin:0}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
.eyebrow{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.16em;
         text-transform:uppercase;color:var(--geo);margin:0 0 6px}
.muted{color:var(--ink-3)} .sub{color:var(--ink-2)}
.sec-title{font-size:26px;line-height:1.15;margin-bottom:2px}
.sec-head{display:flex;align-items:flex-end;justify-content:space-between;
          border-bottom:2px solid var(--ink);padding-bottom:10px;margin-bottom:20px}
.foot{position:absolute;bottom:12mm;left:20mm;right:20mm;display:flex;
      justify-content:space-between;align-items:center;font-family:ui-monospace,Menlo,monospace;
      font-size:10px;color:var(--ink-3);border-top:1px solid var(--line);padding-top:8px}
.prov{display:flex;gap:8px;color:var(--ink-3);font-size:9.5px}
.prov span{border:1px solid var(--line);border-radius:20px;padding:1px 8px}
.cap{font-style:italic;color:var(--ink-3);font-size:12px;margin-top:8px}
.cover{background:var(--ink);color:#eef1ea;border:none}
.cover h1{color:#f3f5ee}
.contour{position:absolute;inset:0;overflow:hidden;opacity:.16}
.cover-inner{position:relative;z-index:2;height:100%;display:flex;flex-direction:column;min-height:252mm}
.badge-gov{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.14em;
           text-transform:uppercase;color:#8fc3bb}
.cover-title{font-size:52px;line-height:1.04;font-weight:600;margin:10px 0 0;letter-spacing:-.01em}
.cover-rule{width:64px;height:3px;background:#5fb3a6;margin:26px 0}
.cover-meta{display:grid;grid-template-columns:1fr 1fr;gap:20px 40px;max-width:520px}
.cover-meta .k{font-family:ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:.12em;
               text-transform:uppercase;color:#7fb0a8}
.cover-meta .v{font-size:17px}
.status-strip{margin-top:auto;display:flex;border-radius:10px;overflow:hidden;
              border:1px solid rgba(255,255,255,.14)}
.status-strip div{flex:1;padding:12px 10px;font-size:11.5px;text-align:center;
                  font-family:ui-monospace,Menlo,monospace}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.soft{background:#faf8f2}
.kpi{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#faf8f2}
.kpi .lab{font-size:12px;color:var(--ink-3);margin-bottom:4px}
.kpi .val{font-family:Georgia,serif;font-size:32px;font-weight:600;line-height:1}
.kpi .val small{font-size:15px;font-weight:500;color:var(--ink-2)}
.kpi .delta{font-family:ui-monospace,Menlo,monospace;font-size:11px;margin-top:6px;color:var(--ink-3)}
.callout{border-left:4px solid var(--geo);background:var(--geo-soft);
         border-radius:0 10px 10px 0;padding:14px 18px}
.warn{border-left-color:var(--high);background:var(--high-bg)}
table.dt{width:100%;border-collapse:collapse;font-size:13px}
table.dt th{text-align:left;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;
            letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);
            border-bottom:1.5px solid var(--ink);padding:8px 10px}
table.dt td{padding:8px 10px;border-bottom:1px solid var(--line)}
table.dt tr:last-child td{border-bottom:none}
.pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 9px;border-radius:20px;
      font-family:ui-monospace,Menlo,monospace}
.p-low{background:var(--low-bg);color:#2f6b2f} .p-mod{background:var(--mod-bg);color:#8a5f10}
.p-high{background:var(--high-bg);color:#8f3f18} .p-sev{background:var(--sev-bg);color:#7d211c}
.legend{display:flex;gap:14px;align-items:center;font-size:11.5px;color:var(--ink-2);flex-wrap:wrap}
.legend span{display:flex;align-items:center;gap:5px}
.sw{width:12px;height:12px;border-radius:3px}
.cal-wrap{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.cal h4{font-size:14px;margin-bottom:8px}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
.cal-cell{aspect-ratio:1;border-radius:3px;background:#eceadf}
.cal-dow{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px}
.cal-dow span{text-align:center;font-size:9px;color:var(--ink-3);
              font-family:ui-monospace,Menlo,monospace;display:block}
.tl{position:relative;margin-left:8px;padding-left:22px;border-left:2px solid var(--line-2)}
.tl-item{position:relative;padding:0 0 14px 4px}
.tl-date{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--ink-3)}
.tl-item h4{font-size:14px;margin:2px 0 3px}
.tl-dot{position:absolute;left:-29px;top:3px;width:12px;height:12px;border-radius:50%;
        border:2px solid #fff}
ul.clean{margin:6px 0;padding-left:0;list-style:none}
ul.clean li{padding:7px 0 7px 24px;position:relative;border-bottom:1px solid var(--line);font-size:13.5px}
ul.clean li:last-child{border-bottom:none}
ul.clean li::before{content:"\\2192";position:absolute;left:0;color:var(--geo);
                    font-family:ui-monospace,Menlo,monospace}
.toolbar{max-width:210mm;margin:16px auto 0;display:flex;gap:10px;align-items:center;
         justify-content:space-between}
.btn{font-size:13px;border:1px solid var(--line-2);background:var(--card);color:var(--ink);
     padding:8px 16px;border-radius:8px;cursor:pointer}
.note{background:#fbf0d8;border:1px solid #ecd9a6;color:#7a5a12;font-size:12.5px;
      padding:8px 14px;border-radius:8px}
.bar-row{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}
.bar-row .nm{width:150px;flex:none}
.bar-track{flex:1;height:14px;background:#eceadf;border-radius:3px;overflow:hidden}
.bar-fill{height:100%}
.bar-row .vv{width:56px;text-align:right;font-family:ui-monospace,Menlo,monospace;font-size:11.5px}
"""

LEVEL_COLOR = {"LOW": "#4a9d4a", "MODERATE": "#e6a52a", "HIGH": "#d1642e", "CRITICAL": "#b5342e"}
LEVEL_PILL = {"LOW": "p-low", "MODERATE": "p-mod", "HIGH": "p-high", "CRITICAL": "p-sev"}
SEV_COLOR = {"INFORMATION": "#6b7b77", "MODERATE": "#e6a52a",
             "HIGH": "#d1642e", "CRITICAL": "#b5342e"}


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _band(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MODERATE"
    return "LOW"


# --------------------------------------------------------------------------- #
# SVG primitives
# --------------------------------------------------------------------------- #
def line_chart(series: list[dict], w=520, h=170, pad=28) -> str:
    """Multi-series line chart. `series` = [{name, color, points:[(x,y)], max}]."""
    if not series or not any(s["points"] for s in series):
        return _empty_chart(w, h, "No readings recorded for this period")
    n = max(len(s["points"]) for s in series)
    body_w, body_h = w - pad * 2, h - pad * 2
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">']
    for i in range(5):
        y = pad + body_h * i / 4
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" '
                   f'stroke="#e2ded2" stroke-width="1"/>')
    for s in series:
        pts = s["points"]
        if not pts:
            continue
        top = s.get("max") or max((p for p in pts), default=1) or 1
        coords = []
        for i, val in enumerate(pts):
            x = pad + (body_w * i / max(1, n - 1))
            y = pad + body_h - (min(val, top) / top) * body_h
            coords.append(f"{x:.1f},{y:.1f}")
        out.append(f'<polyline fill="none" stroke="{s["color"]}" stroke-width="2" '
                   f'stroke-linejoin="round" points="{" ".join(coords)}"/>')
    for i, s in enumerate(series):
        x = pad + i * 132
        out.append(f'<rect x="{x}" y="{h-14}" width="9" height="9" fill="{s["color"]}" rx="2"/>'
                   f'<text x="{x+14}" y="{h-6}" font-size="10" fill="#6b7b77">{e(s["name"])}</text>')
    out.append("</svg>")
    return "".join(out)


def bar_chart(labels: list[str], values: list[float], colors: list[str] | None = None,
              w=520, h=170, pad=28) -> str:
    if not values or max(values, default=0) == 0:
        return _empty_chart(w, h, "No values recorded for this period")
    body_w, body_h = w - pad * 2, h - pad * 2 - 12
    top = max(values) * 1.12 or 1
    bw = body_w / max(1, len(values))
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">']
    for i, v in enumerate(values):
        bh = (v / top) * body_h
        x = pad + i * bw + bw * 0.18
        y = pad + body_h - bh
        col = (colors[i] if colors and i < len(colors) else "#0f5a52")
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw*0.64:.1f}" height="{max(1,bh):.1f}" '
                   f'fill="{col}" rx="2"/>')
        if len(values) <= 14:
            out.append(f'<text x="{x + bw*0.32:.1f}" y="{h-14}" font-size="9" fill="#6b7b77" '
                       f'text-anchor="middle">{e(labels[i])}</text>')
            out.append(f'<text x="{x + bw*0.32:.1f}" y="{y-4:.1f}" font-size="9.5" '
                       f'fill="#3f504c" text-anchor="middle">{v:g}</text>')
    out.append(f'<line x1="{pad}" y1="{pad+body_h}" x2="{w-pad}" y2="{pad+body_h}" '
               f'stroke="#cfcabb" stroke-width="1"/></svg>')
    return "".join(out)


def combo_chart(rain: list[float], risk: list[float], threshold: float,
                w=520, h=190, pad=30) -> str:
    """Rainfall bars behind a risk line, with the district threshold marked.

    One frame rather than two stacked charts: the whole question is whether risk
    followed the rain, and separate axes on separate charts make the reader do the
    correlation by eye across a page break.
    """
    if not rain and not risk:
        return _empty_chart(w, h, "No rainfall or risk history for this period")
    body_w, body_h = w - pad * 2, h - pad * 2
    n = max(len(rain), len(risk), 1)
    rain_top = max(max(rain, default=0), threshold * 1.25, 1)
    bw = body_w / n
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">']
    for i in range(5):
        y = pad + body_h * i / 4
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w-pad}" y2="{y:.1f}" '
                   f'stroke="#eceadf" stroke-width="1"/>')
    for i, v in enumerate(rain):
        bh = (v / rain_top) * body_h
        out.append(f'<rect x="{pad + i*bw + bw*0.12:.1f}" y="{pad + body_h - bh:.1f}" '
                   f'width="{max(1.2, bw*0.76):.1f}" height="{max(0.6, bh):.1f}" '
                   f'fill="#a8c6d8" rx="1"/>')
    ty = pad + body_h - (min(threshold, rain_top) / rain_top) * body_h
    out.append(f'<line x1="{pad}" y1="{ty:.1f}" x2="{w-pad}" y2="{ty:.1f}" stroke="#b5342e" '
               f'stroke-width="1.2" stroke-dasharray="5 4"/>'
               f'<text x="{w-pad}" y="{ty-5:.1f}" font-size="9.5" fill="#b5342e" '
               f'text-anchor="end">24h alert threshold {threshold:.0f} mm</text>')
    if risk:
        coords = []
        for i, v in enumerate(risk):
            x = pad + bw * i + bw / 2
            y = pad + body_h - (min(v, 100) / 100) * body_h
            coords.append(f"{x:.1f},{y:.1f}")
        out.append(f'<polyline fill="none" stroke="#0f5a52" stroke-width="2" '
                   f'points="{" ".join(coords)}"/>')
    out.append('<rect x="30" y="4" width="9" height="9" fill="#a8c6d8" rx="2"/>'
               '<text x="44" y="12" font-size="10" fill="#6b7b77">Rainfall (mm)</text>'
               '<rect x="140" y="4" width="9" height="9" fill="#0f5a52" rx="2"/>'
               '<text x="154" y="12" font-size="10" fill="#6b7b77">Risk score (0-100)</text>')
    out.append("</svg>")
    return "".join(out)


def donut(parts: list[tuple[str, float, str]], w=200, h=170) -> str:
    total = sum(p[1] for p in parts) or 1
    cx, cy, r, thick = w / 2, h / 2 - 6, 52, 20
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">']
    angle = -math.pi / 2
    for label, value, colour in parts:
        if value <= 0:
            continue
        sweep = 2 * math.pi * value / total
        end = angle + sweep
        large = 1 if sweep > math.pi else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
        out.append(f'<path d="M {x1:.1f} {y1:.1f} A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f}" '
                   f'fill="none" stroke="{colour}" stroke-width="{thick}"/>')
        angle = end
    out.append(f'<text x="{cx}" y="{cy+5}" font-size="22" text-anchor="middle" '
               f'font-family="Georgia,serif" fill="#16211f">{int(total)}</text>')
    out.append(f'<text x="{cx}" y="{h-6}" font-size="10" text-anchor="middle" '
               f'fill="#6b7b77">total</text></svg>')
    return "".join(out)


def _empty_chart(w: int, h: int, message: str) -> str:
    """An explicit, specific statement beats a blank frame or the words "no data"."""
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">'
            f'<rect x="1" y="1" width="{w-2}" height="{h-2}" fill="#faf8f2" stroke="#e2ded2" '
            f'rx="8"/><text x="{w/2}" y="{h/2}" font-size="12" fill="#6b7b77" '
            f'text-anchor="middle">{e(message)}</text></svg>')


def bars(rows: list[tuple[str, float, str]], maximum: float | None = None) -> str:
    """Horizontal labelled bars — the densest honest way to rank a dozen items."""
    if not rows:
        return '<p class="muted" style="font-size:13px">Nothing recorded in this scope.</p>'
    top = maximum or max((r[1] for r in rows), default=1) or 1
    out = []
    for name, value, colour in rows:
        pct = min(100, value / top * 100)
        out.append(f'<div class="bar-row"><span class="nm">{e(name)}</span>'
                   f'<span class="bar-track"><span class="bar-fill" '
                   f'style="width:{pct:.1f}%;background:{colour}"></span></span>'
                   f'<span class="vv">{value:g}</span></div>')
    return "".join(out)


def foot(title: str, page: int, provenance: list[str]) -> str:
    chips = "".join(f"<span>{e(p)}</span>" for p in provenance)
    return (f'<div class="foot"><span>{e(title)}</span>'
            f'<div class="prov">{chips}</div><span>Page {page}</span></div>')


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #
def render(report: dict, corridor: dict | None = None) -> str:
    scope = report.get("scope", "North Eastern Region")
    title = f"{scope} \u2014 Landslide Early Warning Quarterly Report"
    kpis = {k["key"]: k for k in report.get("kpis", [])}
    trend = report.get("risk_trend", []) or []
    calendar = report.get("risk_calendar", []) or []
    hist = report.get("historical_context", {}) or {}
    generated = report.get("generated_at", "")[:16].replace("T", " ")

    peak = max((c["risk_score"] for c in calendar), default=0)
    current = trend[-1]["risk_score"] if trend else 0
    alerts_total = sum(a["count"] for a in report.get("alerts_by_severity", []))
    uptime = kpis.get("uptime", {}).get("value", "0")

    pages = [
        _cover(report, scope, peak, alerts_total, uptime, generated),
        _executive(report, kpis, trend, current, peak, title),
        _calendar(report, calendar, title),
        _rainfall(report, trend, title),
        _spatial(report, corridor, title),
        _exposure(report, title),
        _sensors(report, title),
        _model(report, title),
        _districts(report, title),
        _methodology(report, hist, title),
    ]

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}</title><style>{CSS}</style></head><body>
<div class="toolbar noprint">
  <span class="note">Research prototype. Figures are computed from the platform's
  own records: historical dataset, simulated telemetry, model output and verified
  field reports. Provenance is marked on every page.</span>
  <button class="btn" onclick="window.print()">Print / Save as PDF</button>
</div>
{"".join(pages)}
</body></html>"""


def _cover(report, scope, peak, alerts_total, uptime, generated) -> str:
    level = _band(peak)
    return f"""
<section class="page cover">
  <div class="contour"><svg width="100%" height="100%" viewBox="0 0 600 850"
    preserveAspectRatio="xMidYMid slice"><g fill="none" stroke="#8fc3bb" stroke-width="1.1">
    <path d="M-40 120 C120 60 260 180 380 120 S560 40 660 120"/>
    <path d="M-40 190 C120 130 260 250 380 190 S560 110 660 190"/>
    <path d="M-40 270 C140 210 260 340 400 270 S560 190 660 270"/>
    <path d="M-40 360 C120 300 280 430 400 360 S560 280 660 360"/>
    <path d="M-40 460 C150 400 260 540 420 460 S560 380 660 460"/>
    <path d="M-40 560 C120 500 300 640 420 560 S560 480 660 560"/>
    <path d="M-40 660 C160 600 260 740 420 660 S560 580 660 660"/>
    <path d="M-40 760 C120 700 300 840 440 760 S560 680 660 760"/></g></svg></div>
  <div class="cover-inner">
    <div class="badge-gov">NER Landslide Early Warning Platform \u00b7 Risk Intelligence</div>
    <h1 class="cover-title">Landslide<br>Early Warning<br>Quarterly Report</h1>
    <div class="cover-rule"></div>
    <div class="cover-meta">
      <div><div class="k">Reporting period</div><div class="v">{e(report.get('period_label'))}</div></div>
      <div><div class="k">Coverage</div><div class="v">{e(scope)}</div></div>
      <div><div class="k">Generated</div><div class="v">{e(generated)} UTC</div></div>
      <div><div class="k">Report reference</div><div class="v mono">{e(report.get('id'))}</div></div>
    </div>
    <div style="margin-top:30px;max-width:520px;font-size:14px;color:#c7d3cf;line-height:1.6">
      This report summarises where landslide risk concentrated across the reporting
      quarter, how the sensor network performed, which alerts were issued and how
      they were handled, and how the risk model scored against recorded events.
    </div>
    <div class="status-strip">
      <div style="background:#2f6b2f">NETWORK {e(uptime)}%</div>
      <div style="background:{LEVEL_COLOR[level]}">PEAK RISK: {e(level)}</div>
      <div style="background:#8a5f10">PEAK SCORE {int(peak)}</div>
      <div style="background:#123f39">{alerts_total} ALERTS</div>
    </div>
  </div>
</section>"""


def _executive(report, kpis, trend, current, peak, title) -> str:
    level = _band(peak)
    kpi_cards = []
    for key in ("alerts", "detection", "uptime", "response",
                "high-risk-events", "false-alarms"):
        k = kpis.get(key)
        if not k:
            continue
        unit = f"<small>{e(k.get('unit'))}</small>" if k.get("unit") else ""
        kpi_cards.append(
            f'<div class="kpi"><div class="lab">{e(k["label"])}</div>'
            f'<div class="val">{e(k["value"])}{unit}</div>'
            f'<div class="delta">{e(k.get("note", ""))[:60]}</div></div>')

    risk_series = [{"name": "Mean risk score", "color": "#0f5a52", "max": 100,
                    "points": [t["risk_score"] for t in trend]}]
    observations = [
        f"Peak recorded risk for the period was {int(peak)} ({level.title()} band).",
        f"Latest scored risk stands at {int(current)}.",
    ]
    sev = {a["severity"]: a["count"] for a in report.get("alerts_by_severity", [])}
    if sev.get("CRITICAL"):
        observations.append(f"{sev['CRITICAL']} alerts reached the Critical band.")
    exposure = report.get("exposure_detail", [])
    if exposure:
        observations.append(
            f"Highest-exposure asset: {exposure[0]['name']} "
            f"({exposure[0]['risk_level'].title()} risk, {exposure[0]['importance'].title()} importance).")
    reports_pending = report.get("historical_context", {}).get("events")
    if reports_pending:
        observations.append(
            f"{reports_pending} events in the historical record for this scope.")

    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">01 \u2014 At a glance</p>
    <h2 class="sec-title">Executive summary</h2></div>
    <div class="mono muted" style="font-size:11px">{e(report.get('period_label'))}</div></div>
  <div class="callout {'warn' if level in ('HIGH','CRITICAL') else ''}" style="margin-bottom:18px">
    <strong>Peak risk this period: {e(level.title())}.</strong>
    {e(report.get('scope'))} recorded a peak score of {int(peak)} against a latest
    score of {int(current)}. The platform issued
    {sum(a['count'] for a in report.get('alerts_by_severity', []))} alerts across all
    severity bands during the period.
  </div>
  <div class="grid-3" style="margin-bottom:20px">{''.join(kpi_cards)}</div>
  <div class="grid-2">
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">Risk trend</p>
      {line_chart(risk_series)}</div>
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">What the period recorded</p>
      <ul class="clean">{''.join(f'<li>{e(o)}</li>' for o in observations)}</ul></div>
  </div>
  {foot(title, 2, ['Model-derived', 'Historical', 'Simulated'])}
</section>"""


def _calendar(report, calendar, title) -> str:
    months: dict[str, list[dict]] = {}
    for c in calendar:
        key = c["date"][:7]
        months.setdefault(key, []).append(c)

    blocks = []
    for key in sorted(months)[-3:]:
        cells = []
        for c in months[key]:
            colour = LEVEL_COLOR[c["risk_level"]]
            cells.append(f'<div class="cal-cell" style="background:{colour}" '
                         f'title="{e(c["date"][:10])}: {c["risk_score"]}"></div>')
        label = datetime.strptime(key, "%Y-%m").strftime("%B %Y")
        blocks.append(
            f'<div class="cal"><h4>{e(label)}</h4>'
            f'<div class="cal-dow"><span>S</span><span>M</span><span>T</span><span>W</span>'
            f'<span>T</span><span>F</span><span>S</span></div>'
            f'<div class="cal-grid">{"".join(cells)}</div></div>')

    if not blocks:
        blocks = ['<p class="muted" style="font-size:13px">No scored days recorded yet for '
                  'this scope. The calendar fills as the risk engine writes history.</p>']

    sev_rows = report.get("alerts_by_severity", [])
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">02 \u2014 The period in one view</p>
    <h2 class="sec-title">Risk calendar</h2></div>
    <div class="mono muted" style="font-size:11px">daily mean risk</div></div>
  <p class="sub" style="margin-top:0;margin-bottom:16px">Every square is one scored
  day, shaded by that day's mean risk across the zones in scope.</p>
  <div class="cal-wrap">{''.join(blocks)}</div>
  <div class="legend" style="justify-content:center;margin-top:16px">
    <span><span class="sw" style="background:var(--low)"></span>Low</span>
    <span><span class="sw" style="background:var(--mod)"></span>Moderate</span>
    <span><span class="sw" style="background:var(--high)"></span>High</span>
    <span><span class="sw" style="background:var(--sev)"></span>Critical</span></div>
  <div class="card soft" style="margin-top:22px">
    <p class="eyebrow" style="margin-bottom:10px">Alerts issued by severity</p>
    {bar_chart([s['severity'].title() for s in sev_rows],
               [s['count'] for s in sev_rows],
               [SEV_COLOR.get(s['severity'], '#0f5a52') for s in sev_rows])}
  </div>
  {foot(title, 3, ['Model-derived', 'Simulated'])}
</section>"""


def _rainfall(report, trend, title) -> str:
    rvr = report.get("rainfall_vs_risk", []) or []
    threshold = rvr[0]["threshold"] if rvr else 95.0
    hist = report.get("historical_context", {}) or {}
    ev = hist.get("rainfall_on_event_days", {})
    qt = hist.get("rainfall_on_quiet_days", {})

    comparison = ""
    if ev and qt:
        comparison = f"""
    <table class="dt" style="margin-top:6px">
      <tr><th>Window</th><th>Days with an event</th><th>Days without</th><th>Separation</th></tr>
      <tr><td>24-hour rainfall</td><td>{ev.get('mean_24h_mm', 0)} mm</td>
          <td>{qt.get('mean_24h_mm', 0)} mm</td>
          <td class="mono">{ev.get('mean_24h_mm', 0) - qt.get('mean_24h_mm', 0):+.1f}</td></tr>
      <tr><td>72-hour rainfall</td><td>{ev.get('mean_72h_mm', 0)} mm</td>
          <td>{qt.get('mean_72h_mm', 0)} mm</td>
          <td class="mono">{ev.get('mean_72h_mm', 0) - qt.get('mean_72h_mm', 0):+.1f}</td></tr>
      <tr><td>7-day rainfall</td><td>{ev.get('mean_7d_mm', 0)} mm</td>
          <td>{qt.get('mean_7d_mm', 0)} mm</td>
          <td class="mono">{ev.get('mean_7d_mm', 0) - qt.get('mean_7d_mm', 0):+.1f}</td></tr>
      <tr><td>Soil moisture</td><td>{ev.get('mean_soil_moisture_pct', 0)}%</td>
          <td>{qt.get('mean_soil_moisture_pct', 0)}%</td>
          <td class="mono">{ev.get('mean_soil_moisture_pct', 0) - qt.get('mean_soil_moisture_pct', 0):+.1f}</td></tr>
    </table>
    <p class="cap">Antecedent wetness separates event days from quiet days more
    cleanly than any single day's rainfall. That is the empirical basis for the
    combined rule (R2) rather than a rainfall threshold alone.</p>"""

    monthly = hist.get("monthly_events", [])
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">03 \u2014 The trigger</p>
    <h2 class="sec-title">Rainfall and risk</h2></div>
    <div class="mono muted" style="font-size:11px">against the district threshold</div></div>
  <div class="card soft" style="margin-bottom:18px">
    <p class="eyebrow" style="margin-bottom:8px">Rainfall against risk score</p>
    {combo_chart([r['rainfall'] for r in rvr], [r['risk_score'] for r in rvr], threshold)}
    <p class="cap">Risk follows accumulation rather than any single day's fall;
    the lag between a heavy spell and the risk peak is the warning window.</p>
  </div>
  <div class="grid-2">
    <div class="card"><p class="eyebrow" style="margin-bottom:8px">Rainfall on event days
      vs quiet days</p>{comparison or '<p class="muted" style="font-size:13px">Historical dataset not loaded in this deployment.</p>'}</div>
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">Recorded events by month</p>
      {bar_chart([m['month'] for m in monthly], [m['events'] for m in monthly])
       if monthly else _empty_chart(520, 170, 'Historical dataset not loaded')}
      <p class="cap">Monsoon concentration, {e(hist.get('scope', 'region'))}.</p></div>
  </div>
  {foot(title, 4, ['Historical', 'Simulated', 'Model-derived'])}
</section>"""


def _spatial(report, corridor, title) -> str:
    if corridor and corridor.get("available"):
        priority = corridor.get("priority_assets", [])[:6]
        rows = "".join(
            f'<tr><td>{e(p.get("asset_name"))}</td>'
            f'<td class="muted">{e(p.get("asset_type"))}</td>'
            f'<td class="mono">{p.get("max_hazard_risk", 0):.1f}</td>'
            f'<td><span class="pill {LEVEL_PILL[_band(p.get("priority_score", 0))]}">'
            f'{p.get("priority_score", 0):.1f}</span></td></tr>'
            for p in priority)
        body = f"""
  <div class="grid-4" style="margin-bottom:16px">
    <div class="kpi"><div class="lab">Elevation range</div>
      <div class="val">{int(corridor.get('elevation_min_m') or 0)}<small>\u2013{int(corridor.get('elevation_max_m') or 0)} m</small></div></div>
    <div class="kpi"><div class="lab">Mean corridor risk</div>
      <div class="val">{corridor.get('mean_risk') or 0}</div></div>
    <div class="kpi"><div class="lab">Exposed road</div>
      <div class="val">{corridor.get('exposed_road_km') or 0}<small> km</small></div></div>
    <div class="kpi"><div class="lab">Threatened population</div>
      <div class="val">{corridor.get('threatened_population') or 0}</div></div>
  </div>
  <p class="sub" style="margin-top:0">{e(corridor.get('name'))} \u2014
     {e(corridor.get('scenario') or 'current state')},
     grid resolution {e(corridor.get('cell_size_m'))} m.</p>
  <table class="dt" style="margin-top:10px">
    <tr><th>Asset</th><th>Class</th><th>Max hazard</th><th>Priority score</th></tr>
    {rows}</table>
  <p class="cap">Priority score = hazard risk \u00d7 asset criticality \u00d7 vulnerability,
  computed by the spatial exposure engine over the DEM-derived risk surface.</p>"""
    else:
        zones = report.get("district_comparison", [])[:8]
        body = f"""
  <p class="sub" style="margin-top:0">Zone-level spatial risk for this scope. The
  surveyed corridor raster covers the Kohima\u2013Dimapur alignment; elsewhere risk is
  reported per scored slope unit.</p>
  {bars([(z['district'], z['risk_score'], LEVEL_COLOR[_band(z['risk_score'])]) for z in zones], 100)}"""

    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">04 \u2014 Where</p>
    <h2 class="sec-title">Spatial risk</h2></div>
    <div class="mono muted" style="font-size:11px">DEM-derived</div></div>
  {body}
  {foot(title, 5, ['Model-derived', 'GIS'])}
</section>"""


def _exposure(report, title) -> str:
    impact = report.get("infrastructure_impact", [])
    detail = report.get("exposure_detail", [])[:10]
    rows = "".join(
        f'<tr><td>{e(i["name"])}</td><td class="muted">{e(i["type"].title())}</td>'
        f'<td>{e(i["district"])}</td>'
        f'<td><span class="pill {LEVEL_PILL.get(i["risk_level"], "p-low")}">{e(i["risk_level"].title())}</span></td>'
        f'<td class="mono">{i["exposure_score"]}</td></tr>'
        for i in detail)
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">05 \u2014 What is exposed</p>
    <h2 class="sec-title">Infrastructure exposure</h2></div>
    <div class="mono muted" style="font-size:11px">risk \u00d7 importance</div></div>
  <div class="grid-2" style="margin-bottom:18px">
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">Assets exposed by class</p>
      {bar_chart([i['type'].title()[:8] for i in impact], [i['exposed'] for i in impact])}</div>
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">Critically exposed by class</p>
      {bar_chart([i['type'].title()[:8] for i in impact], [i['critical'] for i in impact],
                 ['#b5342e'] * len(impact))}</div>
  </div>
  <p class="eyebrow">Highest exposure scores</p>
  <table class="dt"><tr><th>Asset</th><th>Class</th><th>District</th>
    <th>Slope risk</th><th>Exposure</th></tr>{rows or
    '<tr><td colspan="5" class="muted">No infrastructure recorded in this scope.</td></tr>'}</table>
  <p class="cap">Exposure ranks which asset receives the one available inspection
  crew. It is not a prediction that the asset will fail.</p>
  {foot(title, 6, ['Model-derived', 'GIS'])}
</section>"""


def _sensors(report, title) -> str:
    perf = report.get("sensor_performance", [])
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">06 \u2014 Can we see?</p>
    <h2 class="sec-title">Sensor performance</h2></div>
    <div class="mono muted" style="font-size:11px">uptime and health</div></div>
  <p class="sub" style="margin-top:0;margin-bottom:16px">A high risk reading and an
  unreliable instrument look identical in raw data. Health is scored independently
  of risk and travels with it, so an alert can be marked low-confidence and routed
  for human checking rather than being either trusted or silently dropped.</p>
  <div class="grid-2">
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">Fleet uptime (%)</p>
      {bar_chart([p['month'] for p in perf], [p['uptime_pct'] for p in perf])}</div>
    <div class="card soft"><p class="eyebrow" style="margin-bottom:8px">Mean health score</p>
      {bar_chart([p['month'] for p in perf], [p['mean_health'] for p in perf],
                 ['#0f5a52'] * len(perf))}</div>
  </div>
  <div class="card" style="margin-top:18px">
    <p class="eyebrow" style="margin-bottom:8px">Health score composition</p>
    <table class="dt">
      <tr><th>Component</th><th>Weight</th><th>What it detects</th></tr>
      <tr><td>Completeness</td><td class="mono">0.25</td><td>Missed reporting intervals</td></tr>
      <tr><td>Validity</td><td class="mono">0.25</td><td>Readings outside the physical range</td></tr>
      <tr><td>Stability</td><td class="mono">0.20</td><td>Calibration drift \u2014 a probe walking away from truth</td></tr>
      <tr><td>Noise</td><td class="mono">0.15</td><td>High-frequency jitter against signal level</td></tr>
      <tr><td>Communications</td><td class="mono">0.15</td><td>Battery state and uplink strength</td></tr>
    </table>
    <p class="cap">A silent sensor is scored offline regardless of how clean its
    last reading looked: eight missed intervals force the status.</p>
  </div>
  {foot(title, 7, ['Simulated', 'Model-derived'])}
</section>"""


def _model(report, title) -> str:
    mp = report.get("model_performance") or {}
    if not mp:
        body = ('<p class="muted">No model run registered for this period. The rule '
                'engine supplied every score in this report.</p>')
    else:
        fi = mp.get("feature_importance", [])[:8]
        metrics = [("ROC AUC", mp.get("roc_auc")), ("Accuracy", mp.get("accuracy")),
                   ("Precision", mp.get("precision")), ("Recall", mp.get("recall")),
                   ("F1", mp.get("f1"))]
        cards = "".join(
            f'<div class="kpi"><div class="lab">{e(n)}</div>'
            f'<div class="val">{(v if isinstance(v, (int, float)) else 0):.3f}</div></div>'
            for n, v in metrics if v is not None)
        body = f"""
  <div class="grid-3" style="margin-bottom:18px">{cards}</div>
  <div class="card soft"><p class="eyebrow" style="margin-bottom:10px">Feature importance</p>
    {bars([(f.get('feature', '?'), round(float(f.get('importance', 0)), 3), '#0f5a52') for f in fi])}
  </div>
  <div class="callout" style="margin-top:18px">
    <strong>Selected model: {e(mp.get('selected_model', 'n/a'))}.</strong>
    Evaluated on {e(mp.get('evaluated_on', 'held-out data'))}.
    {e(mp.get('caveat', ''))}
  </div>
  <p class="cap">Recall is deliberately favoured over precision. For early warning
  a missed event costs more than a false alarm \u2014 but only up to the point where
  false alarms train a district to ignore the sender, which is what the cooldown,
  deduplication and tier-routing rules exist to prevent.</p>"""
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">07 \u2014 Does it work?</p>
    <h2 class="sec-title">Model performance</h2></div>
    <div class="mono muted" style="font-size:11px">held-out evaluation</div></div>
  {body}
  {foot(title, 8, ['Model-derived'])}
</section>"""


def _districts(report, title) -> str:
    comp = report.get("district_comparison", [])[:10]
    rows = "".join(
        f'<tr><td>{e(c["district"])}</td>'
        f'<td><span class="pill {LEVEL_PILL[_band(c["risk_score"])]}">{c["risk_score"]}</span></td>'
        f'<td class="mono">{c["alerts"]}</td><td class="mono">{c["incidents"]}</td></tr>'
        for c in comp)
    events = report.get("critical_events", [])
    timeline = "".join(
        f'<div class="tl-item"><span class="tl-dot" '
        f'style="background:{LEVEL_COLOR.get(ev["severity"], "#6b7b77")}"></span>'
        f'<div class="tl-date">{e(ev["date"][:10])} \u00b7 {e(ev["district"])}</div>'
        f'<h4>{e(ev["title"].title())}</h4>'
        f'<div class="muted" style="font-size:12.5px">{e(ev["note"])}</div></div>'
        for ev in events)
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">08 \u2014 Comparison</p>
    <h2 class="sec-title">Districts and critical events</h2></div>
    <div class="mono muted" style="font-size:11px">{e(report.get('period_label'))}</div></div>
  <table class="dt" style="margin-bottom:22px">
    <tr><th>District</th><th>Mean risk</th><th>Alerts</th><th>Recorded events</th></tr>
    {rows or '<tr><td colspan="4" class="muted">No districts in scope.</td></tr>'}</table>
  <p class="eyebrow">Critical and high-severity events</p>
  <div class="tl">{timeline or
    '<p class="muted" style="font-size:13px">No critical or high-severity events recorded in this scope for the period.</p>'}</div>
  {foot(title, 9, ['Historical', 'User-reported'])}
</section>"""


def _methodology(report, hist, title) -> str:
    return f"""
<section class="page">
  <div class="sec-head"><div><p class="eyebrow">09 \u2014 Definitions</p>
    <h2 class="sec-title">Methodology and KPIs</h2></div>
    <div class="mono muted" style="font-size:11px">how every figure was computed</div></div>

  <p class="eyebrow">Risk score</p>
  <div class="card soft" style="margin-bottom:16px">
    <p class="mono" style="font-size:13px;margin:0 0 6px">
      risk = (LSI \u00d7 0.4 + TI \u00d7 0.6) \u00d7 100</p>
    <p class="sub" style="margin:0;font-size:13.5px">
      LSI is static susceptibility: slope 40%, soil 25%, landcover 20%, elevation
      and aspect 15%. TI is the dynamic trigger: soil moisture 30%, 24-hour
      rainfall 30%, antecedent precipitation index 15%, 72-hour rainfall 15%,
      7-day rainfall 10%. The dynamic term is weighted higher because a steep
      slope does not slide without rain.</p>
  </div>

  <p class="eyebrow">Alert tiers</p>
  <table class="dt" style="margin-bottom:16px">
    <tr><th>Score</th><th>Tier</th><th>Status</th><th>Recipients</th></tr>
    <tr><td class="mono">0\u201340</td><td><span class="pill p-low">Green</span></td>
        <td>No warning \u2014 normal conditions</td><td class="muted">No message sent</td></tr>
    <tr><td class="mono">41\u201365</td><td><span class="pill p-mod">Yellow</span></td>
        <td>Watch \u2014 landslides possible if rain continues</td>
        <td>District Magistrate, SDRF</td></tr>
    <tr><td class="mono">66\u201385</td><td><span class="pill p-high">Orange</span></td>
        <td>Alert \u2014 high probability of slope failure</td>
        <td>Authorities and local ward members</td></tr>
    <tr><td class="mono">86\u2013100</td><td><span class="pill p-sev">Red</span></td>
        <td>Action \u2014 imminent slope failure risk</td>
        <td>General public, geo-fenced broadcast</td></tr>
  </table>

  <p class="eyebrow">KPI definitions</p>
  <table class="dt" style="margin-bottom:16px">
    <tr><th>KPI</th><th>Definition</th></tr>
    <tr><td>Events preceded by an alert</td>
        <td>Share of recorded events for which an alert was already open at onset.</td></tr>
    <tr><td>Alerts generated</td><td>Distinct alerts created, excluding suppressed
        re-fires inside the cooldown window.</td></tr>
    <tr><td>Sensor uptime</td><td>Share of the fleet reporting with status ONLINE.</td></tr>
    <tr><td>Alerts closed without escalation</td>
        <td>Proxy for false alarms until field outcomes are recorded against each alert.</td></tr>
    <tr><td>Mean response time</td>
        <td>Mean minutes from event onset to recorded field response.</td></tr>
  </table>

  <p class="eyebrow">Data provenance</p>
  <table class="dt">
    <tr><th>Label</th><th>Meaning in this report</th></tr>
    <tr><td>Historical</td><td>{e(hist.get('source', 'Cleaned regional landslide record.'))}
        {e(hist.get('records', 0))} records, {e(hist.get('events', 0))} events,
        reported at state resolution.</td></tr>
    <tr><td>Simulated</td><td>Sensor telemetry produced by the physics-informed
        fleet simulator. Not a field measurement.</td></tr>
    <tr><td>Model-derived</td><td>Risk scores, probabilities and exposure rankings
        computed by the risk and exposure engines.</td></tr>
    <tr><td>User-reported</td><td>Field and citizen reports. Treated as a signal
        and acted on only once verified by an authority.</td></tr>
    <tr><td>GIS</td><td>DEM, terrain derivatives and the spatial risk surface from
        the GIS pipeline export.</td></tr>
  </table>
  <p class="cap">This is a research prototype. It carries no authority to issue an
  official warning, and no figure in this report should be cited as an observation
  without checking its provenance label above.</p>
  {foot(title, 10, ['Historical', 'Simulated', 'Model-derived', 'User-reported'])}
</section>"""
