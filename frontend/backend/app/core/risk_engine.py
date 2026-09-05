"""Risk scoring engine.

Direct implementation of the team's risk-methodology note:

    LSI  = static susceptibility  (slope 40%, soil 25%, landcover 20%, elev/aspect 15%)
    TI   = dynamic trigger        (rainfall 24h/72h/7d, API, soil moisture)
    risk = LSI * 0.4 + TI * 0.6   -> scaled to 0-100

Two deliberate design points worth knowing before you change anything here:

1. This engine is the FALLBACK, not the primary. If the ML model has pushed a
   score for a zone (source == "ML_MODEL"), that score wins and this code is not
   consulted. The engine exists so the platform degrades to a defensible
   physically-grounded number instead of to nothing when the model is unavailable —
   which, for an early-warning system, is the difference between a demo and a product.

2. `explain()` returns the same numbers the score was built from. The UI renders
   contributing factors as weighted meters, and an authority who cannot see why a
   score is high will not act on it. Never return a score without its breakdown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import settings

# --------------------------------------------------------------------------- #
# 1. Categorical lookups
# --------------------------------------------------------------------------- #
SOIL_SCORES = {
    "BEDROCK": 0.1, "SOLID ROCK": 0.1, "ROCK": 0.1,
    "GRAVEL": 0.3, "SAND": 0.3, "SANDY": 0.3,
    "SILTY LOAM": 0.6, "LATERITE": 0.6, "LOAM": 0.6,
    "CLAYEY": 0.9, "CLAY": 0.9, "EXPANSIVE SOIL": 0.9,
}

LANDCOVER_SCORES = {
    "DENSE FOREST": 0.1, "FOREST": 0.15,
    "PLANTATION": 0.4, "AGRICULTURE": 0.4, "SHRUB": 0.45,
    "BUILT-UP": 0.6, "BUILT UP": 0.6, "URBAN": 0.6,
    "BARREN": 0.9, "DEFORESTED": 0.9, "CUT SLOPE": 0.9,
}

# LSI component weights
W_SLOPE, W_SOIL, W_LANDCOVER, W_TERRAIN = 0.40, 0.25, 0.20, 0.15

# TI component weights — soil state and short-burst rain dominate.
W_MOISTURE, W_R24, W_R72, W_R7D, W_API = 0.30, 0.30, 0.15, 0.10, 0.15


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------- #
# 2. Piecewise terrain functions
# --------------------------------------------------------------------------- #
def slope_score(slope_deg: float) -> float:
    """30-45 degrees is the critical failure window for soil slopes.

    Above 45 the score dips: very steep faces are usually exposed bedrock, which
    fails less often than a soil mantle. That non-monotonicity is intentional and
    is the single most common thing people 'fix' by mistake.
    """
    s = max(0.0, float(slope_deg))
    if s < 15:
        return 0.1
    if s < 30:
        return 0.4
    if s <= 45:
        return 0.9
    return 0.7


def soil_moisture_score(pct: float) -> float:
    m = _clamp(float(pct), 0, 100)
    if m < 30:
        return 0.1
    if m <= 60:
        return 0.4
    if m <= 80:
        return 0.4 + (m - 60) * 0.02      # linear ramp 0.4 -> 0.8
    return 0.9


def elevation_score(elev_m: float) -> float:
    """Mid-elevations carry the thickest colluvium, so they score highest."""
    e = float(elev_m)
    if e < 500:
        return 0.2
    if e <= 1500:
        return 0.8
    return 0.4


def aspect_score(aspect_deg: float) -> float:
    """SW-facing slopes (225 deg) take the brunt of the southwest monsoon."""
    raw = 0.5 + 0.5 * math.cos(math.radians(float(aspect_deg) - 225.0))
    return _clamp(raw, 0.2, 1.0)          # floor at 0.2; no aspect is risk-free


def soil_score(soil_type: str | None) -> float:
    return SOIL_SCORES.get((soil_type or "").strip().upper(), 0.6)


def landcover_score(landcover: str | None) -> float:
    return LANDCOVER_SCORES.get((landcover or "").strip().upper(), 0.4)


# --------------------------------------------------------------------------- #
# 3. Rainfall scaling
# --------------------------------------------------------------------------- #
def rainfall_score(value_mm: float, t_crit: float) -> float:
    if t_crit <= 0:
        return 0.0
    return _clamp(float(value_mm) / t_crit)


def antecedent_precipitation_index(
    daily_rainfall_mm: list[float], k: float | None = None
) -> float:
    """API_t = P_t + k * API_(t-1), oldest day first.

    Pure rain-gauge derivation, so it keeps working when the soil-moisture probes
    drop off the network — which in this terrain they will.
    """
    k = settings.api_decay_k if k is None else k
    api = 0.0
    for p in daily_rainfall_mm:
        api = float(p) + k * api
    return round(api, 2)


# --------------------------------------------------------------------------- #
# 4. Composite scores
# --------------------------------------------------------------------------- #
@dataclass
class RiskResult:
    lsi: float
    ti: float
    risk_score: float          # 0-100
    risk_level: str
    alert_tier: str
    probability: float
    contributing_factors: dict[str, float]
    components: dict[str, float]


def compute_lsi(
    slope_deg: float, soil_type: str, landcover: str, elevation_m: float, aspect_deg: float
) -> tuple[float, dict[str, float]]:
    parts = {
        "slope": slope_score(slope_deg),
        "soil": soil_score(soil_type),
        "landcover": landcover_score(landcover),
        # elevation and aspect share the last 15%
        "terrain": 0.6 * elevation_score(elevation_m) + 0.4 * aspect_score(aspect_deg),
    }
    lsi = (
        parts["slope"] * W_SLOPE
        + parts["soil"] * W_SOIL
        + parts["landcover"] * W_LANDCOVER
        + parts["terrain"] * W_TERRAIN
    )
    return round(_clamp(lsi), 4), parts


def compute_ti(
    rainfall_24h_mm: float,
    rainfall_72h_mm: float,
    rainfall_7d_mm: float,
    soil_moisture_pct: float,
    api_value: float,
) -> tuple[float, dict[str, float]]:
    parts = {
        "soil_moisture": soil_moisture_score(soil_moisture_pct),
        "rainfall_24h": rainfall_score(rainfall_24h_mm, settings.t_crit_24h),
        "rainfall_72h": rainfall_score(rainfall_72h_mm, settings.t_crit_72h),
        "rainfall_7d": rainfall_score(rainfall_7d_mm, settings.t_crit_7d),
        "api": rainfall_score(api_value, settings.api_max),
    }
    ti = (
        parts["soil_moisture"] * W_MOISTURE
        + parts["rainfall_24h"] * W_R24
        + parts["rainfall_72h"] * W_R72
        + parts["rainfall_7d"] * W_R7D
        + parts["api"] * W_API
    )
    return round(_clamp(ti), 4), parts


def risk_level_from_score(score: float) -> str:
    b = settings.bands
    if score >= b.critical:
        return "CRITICAL"
    if score >= b.high:
        return "HIGH"
    if score >= b.moderate:
        return "MODERATE"
    return "LOW"


def alert_tier_from_score(score: float) -> str:
    """NDMA/GSI colour tier. Drives who gets an SMS, not what colour the map is."""
    t = settings.tiers
    if score >= t.red:
        return "RED"
    if score >= t.orange:
        return "ORANGE"
    if score >= t.yellow:
        return "YELLOW"
    return "GREEN"


def expected_window_hours(level: str) -> int | None:
    return {"CRITICAL": 6, "HIGH": 12, "MODERATE": 24}.get(level)


RECOMMENDED_ACTION = {
    "CRITICAL": (
        "Evacuate exposed habitations, close the affected road section and stage "
        "NDRF/SDRF response teams."
    ),
    "HIGH": (
        "Restrict night-time traffic, deploy slope inspection team and pre-position "
        "clearing equipment."
    ),
    "MODERATE": "Continue monitoring, inspect drainage and issue advisory to local administration.",
    "LOW": "Routine monitoring. No action required beyond scheduled inspection.",
}


def score_zone(
    *,
    slope_deg: float,
    soil_type: str,
    landcover: str,
    elevation_m: float,
    aspect_deg: float,
    rainfall_24h_mm: float,
    rainfall_72h_mm: float,
    rainfall_7d_mm: float,
    soil_moisture_pct: float,
    antecedent_precip_index: float,
    sensor_confidence: float = 100.0,
) -> RiskResult:
    """Score one zone end to end.

    `sensor_confidence` does NOT reduce the risk score. A slope that is about to
    fail does not become safer because a battery died. It is carried alongside so
    the alert engine can label a warning low-confidence and route it for human
    checking rather than quietly downgrading it.
    """
    lsi, lsi_parts = compute_lsi(slope_deg, soil_type, landcover, elevation_m, aspect_deg)
    ti, ti_parts = compute_ti(
        rainfall_24h_mm, rainfall_72h_mm, rainfall_7d_mm,
        soil_moisture_pct, antecedent_precip_index,
    )

    final = lsi * settings.w_static + ti * settings.w_dynamic
    score = round(_clamp(final) * 100, 1)
    level = risk_level_from_score(score)

    # Probability is a calibrated read of the same composite, not a second model.
    # The mild sigmoid keeps mid-range scores from reading as near-certainties.
    probability = round(_clamp(1 / (1 + math.exp(-8 * (final - 0.55)))), 3)

    # Contributing factors are normalised to sum to 1 so the UI meters are comparable.
    weighted = {
        "slope_deg": lsi_parts["slope"] * W_SLOPE * settings.w_static,
        "soil_type": lsi_parts["soil"] * W_SOIL * settings.w_static,
        "landcover": lsi_parts["landcover"] * W_LANDCOVER * settings.w_static,
        "terrain": lsi_parts["terrain"] * W_TERRAIN * settings.w_static,
        "soil_moisture_pct": ti_parts["soil_moisture"] * W_MOISTURE * settings.w_dynamic,
        "rainfall_24h_mm": ti_parts["rainfall_24h"] * W_R24 * settings.w_dynamic,
        "rainfall_72h_mm": ti_parts["rainfall_72h"] * W_R72 * settings.w_dynamic,
        "rainfall_7d_mm": ti_parts["rainfall_7d"] * W_R7D * settings.w_dynamic,
        "antecedent_precip_index": ti_parts["api"] * W_API * settings.w_dynamic,
    }
    total = sum(weighted.values()) or 1.0
    contributing = {k: round(v / total, 3) for k, v in weighted.items()}

    return RiskResult(
        lsi=lsi,
        ti=ti,
        risk_score=score,
        risk_level=level,
        alert_tier=alert_tier_from_score(score),
        probability=probability,
        contributing_factors=contributing,
        components={**{f"lsi_{k}": v for k, v in lsi_parts.items()},
                    **{f"ti_{k}": v for k, v in ti_parts.items()}},
    )


def explain(result: RiskResult) -> dict:
    """Human-readable breakdown for the zone detail panel and the audit trail."""
    return {
        "lsi": result.lsi,
        "ti": result.ti,
        "weights": {"static": settings.w_static, "dynamic": settings.w_dynamic},
        "formula": "risk = (LSI x w_static + TI x w_dynamic) x 100",
        "components": result.components,
        "contributing_factors": result.contributing_factors,
        "bands": {
            "critical": settings.bands.critical,
            "high": settings.bands.high,
            "moderate": settings.bands.moderate,
        },
        "tiers": {
            "red": settings.tiers.red,
            "orange": settings.tiers.orange,
            "yellow": settings.tiers.yellow,
        },
    }
