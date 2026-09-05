"""Historical event dataset access.

Reads `data/ml/historical_events_cleaned.csv` — the data pipeline's cleaned
regional record — and turns it into the aggregates the quarterly report needs.

Two things this module refuses to do:

* **Invent district resolution.** Every row carries a state and a coordinate but no
  district. Aggregates are therefore reported per state, and a district-scoped
  report says "Assam, 2015-2025" rather than implying the record is local to Dima
  Hasao. A number attributed to the wrong administrative unit is worse than no
  number, because it will be quoted.

* **Present the record as observed fact.** Rows are labelled with their source and
  confidence in the CSV, and that label travels through to the report.

Loaded once and cached. The file is 570 kB; re-parsing it per request would make
report generation feel broken.
"""
from __future__ import annotations

import csv
import logging
import statistics
from functools import lru_cache
from pathlib import Path

from ..config import settings

log = logging.getLogger("ner.historical")

STATE_NAME_TO_CODE = {
    "Assam": "AS", "Arunachal Pradesh": "AR", "Manipur": "MN", "Meghalaya": "ML",
    "Mizoram": "MZ", "Nagaland": "NL", "Sikkim": "SK", "Tripura": "TR",
}

_NUMERIC = ("rainfall_24h_mm", "rainfall_72h_mm", "rainfall_7d_mm",
            "antecedent_precip_index", "soil_moisture_pct", "slope_deg", "elevation_m")


@lru_cache(maxsize=1)
def rows() -> list[dict]:
    path = Path(settings.ml_data_dir) / "historical_events_cleaned.csv"
    if not path.is_file():
        log.warning("historical dataset not found at %s", path)
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rec = dict(r)
            for key in _NUMERIC:
                try:
                    rec[key] = float(rec.get(key) or 0)
                except ValueError:
                    rec[key] = 0.0
            rec["occurred"] = str(rec.get("landslide_occurred", "0")).strip() == "1"
            rec["state_code"] = STATE_NAME_TO_CODE.get(rec.get("state", ""), "")
            out.append(rec)
    return out


def available() -> bool:
    return bool(rows())


def summary(state_code: str | None = None) -> dict:
    """Occurrence rate, rainfall separation and the monthly profile."""
    data = rows()
    if not data:
        return {"available": False,
                "note": "Historical dataset not present in this deployment."}

    scoped = [r for r in data if r["state_code"] == state_code] if state_code else data
    if not scoped:
        scoped = data
        state_code = None

    events = [r for r in scoped if r["occurred"]]
    quiet = [r for r in scoped if not r["occurred"]]

    def mean(seq, key):
        vals = [r[key] for r in seq]
        return round(statistics.fmean(vals), 1) if vals else 0.0

    months: dict[int, int] = {}
    years: dict[int, int] = {}
    for r in events:
        date = (r.get("date") or "")[:10]
        if len(date) == 10:
            months[int(date[5:7])] = months.get(int(date[5:7]), 0) + 1
            years[int(date[:4])] = years.get(int(date[:4]), 0) + 1

    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # The rainfall separation between event and non-event rows is the single most
    # useful figure here: it is the empirical justification for the 24-hour
    # threshold the alert engine actually uses.
    return {
        "available": True,
        "scope": state_code or "NER (all states)",
        "records": len(scoped),
        "events": len(events),
        "occurrence_rate_pct": round(len(events) / len(scoped) * 100, 1) if scoped else 0.0,
        "period": {
            "from": min((r.get("date") or "" for r in scoped), default=""),
            "to": max((r.get("date") or "" for r in scoped), default=""),
        },
        "rainfall_on_event_days": {
            "mean_24h_mm": mean(events, "rainfall_24h_mm"),
            "mean_72h_mm": mean(events, "rainfall_72h_mm"),
            "mean_7d_mm": mean(events, "rainfall_7d_mm"),
            "mean_soil_moisture_pct": mean(events, "soil_moisture_pct"),
        },
        "rainfall_on_quiet_days": {
            "mean_24h_mm": mean(quiet, "rainfall_24h_mm"),
            "mean_72h_mm": mean(quiet, "rainfall_72h_mm"),
            "mean_7d_mm": mean(quiet, "rainfall_7d_mm"),
            "mean_soil_moisture_pct": mean(quiet, "soil_moisture_pct"),
        },
        "mean_slope_deg_on_event_days": mean(events, "slope_deg"),
        "monthly_events": [{"month": labels[m - 1], "events": months.get(m, 0)}
                           for m in range(1, 13)],
        "yearly_events": [{"year": y, "events": years[y]} for y in sorted(years)],
        "source": "Cleaned regional landslide record (data/ml/historical_events_cleaned.csv)",
        "provenance": "Historical \u00b7 synthesised regional record, state resolution",
    }


def state_comparison() -> list[dict]:
    data = rows()
    if not data:
        return []
    by_state: dict[str, list[dict]] = {}
    for r in data:
        by_state.setdefault(r.get("state", "Unknown"), []).append(r)
    out = []
    for name, group in by_state.items():
        events = [r for r in group if r["occurred"]]
        out.append({
            "state": name,
            "state_code": STATE_NAME_TO_CODE.get(name, ""),
            "records": len(group),
            "events": len(events),
            "occurrence_rate_pct": round(len(events) / len(group) * 100, 1),
            "mean_rainfall_24h_on_events": round(
                statistics.fmean([r["rainfall_24h_mm"] for r in events]), 1) if events else 0.0,
        })
    return sorted(out, key=lambda x: -x["events"])
