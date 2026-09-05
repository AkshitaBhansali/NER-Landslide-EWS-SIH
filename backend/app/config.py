"""Runtime configuration.

Everything an operator might need to change for a deployment lives here
and is overridable by environment variable. Nothing in the engines hard-codes a number.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repository root: <root>/backend/app/config.py -> <root>
REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).resolve()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass
class RiskBands:
    """Display bands used by the console (README: >=80 CRITICAL, >=60 HIGH, >=35 MODERATE)."""

    critical: float = field(default_factory=lambda: _f("RISK_BAND_CRITICAL", 80))
    high: float = field(default_factory=lambda: _f("RISK_BAND_HIGH", 60))
    moderate: float = field(default_factory=lambda: _f("RISK_BAND_MODERATE", 35))


@dataclass
class AlertTiers:
    """NDMA/GSI dispatch tiers from the risk-methodology note, expressed on a 0-100 scale.

    These are deliberately NOT the same numbers as RiskBands. The bands answer
    "how bad does this look on screen"; the tiers answer "who gets woken up".
    Keeping them separate is what lets us raise the SMS cut-off without changing
    the colour of every zone on the map.
    """

    red: float = field(default_factory=lambda: _f("TIER_RED", 86))
    orange: float = field(default_factory=lambda: _f("TIER_ORANGE", 66))
    yellow: float = field(default_factory=lambda: _f("TIER_YELLOW", 41))


@dataclass
class Settings:
    app_name: str = "NER Landslide EWS — Backend"
    version: str = "1.0.0"
    env: str = os.getenv("ENV", "development")

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./ner_ews.db")
    media_root: str = os.getenv("MEDIA_ROOT", "./media")

    # --- shared project data -----------------------------------------------
    # These point at the repository's top-level data/ tree, which holds the GIS
    # exports and the ML team's trained model + historical dataset. Nothing is
    # duplicated into the backend package; the backend reads the originals.
    repo_root: Path = REPO_ROOT
    gis_data_dir: Path = field(default_factory=lambda: _path("GIS_DATA_DIR", REPO_ROOT / "data" / "gis"))
    ml_data_dir: Path = field(default_factory=lambda: _path("ML_DATA_DIR", REPO_ROOT / "data" / "ml"))
    report_out_dir: Path = field(default_factory=lambda: _path("REPORT_OUT_DIR", REPO_ROOT / "reports"))

    # Auth is off by default so the console can talk to this with zero setup.
    auth_enabled: bool = field(default_factory=lambda: _b("AUTH_ENABLED", False))
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    jwt_ttl_hours: int = field(default_factory=lambda: _i("JWT_TTL_HOURS", 12))

    cors_origins: str = os.getenv("CORS_ORIGINS", "*")

    # --- risk engine -------------------------------------------------------
    bands: RiskBands = field(default_factory=RiskBands)
    tiers: AlertTiers = field(default_factory=AlertTiers)

    # Final score = LSI * w_static + TI * w_dynamic  (methodology note: 0.4 / 0.6)
    w_static: float = field(default_factory=lambda: _f("W_STATIC", 0.4))
    w_dynamic: float = field(default_factory=lambda: _f("W_DYNAMIC", 0.6))

    # Rainfall critical thresholds (mm) used for min-max scaling.
    t_crit_24h: float = field(default_factory=lambda: _f("T_CRIT_24H", 150))
    t_crit_72h: float = field(default_factory=lambda: _f("T_CRIT_72H", 250))
    t_crit_7d: float = field(default_factory=lambda: _f("T_CRIT_7D", 400))
    api_max: float = field(default_factory=lambda: _f("API_MAX", 200))
    api_decay_k: float = field(default_factory=lambda: _f("API_DECAY_K", 0.85))

    # --- alert engine ------------------------------------------------------
    dispatch_cutoff: float = field(default_factory=lambda: _f("DISPATCH_CUTOFF", 60))
    alert_cooldown_minutes: int = field(default_factory=lambda: _i("ALERT_COOLDOWN_MIN", 45))
    auto_resolve_after_hours: int = field(default_factory=lambda: _i("AUTO_RESOLVE_HOURS", 24))
    # Below this sensor confidence an alert is flagged low-confidence rather than suppressed.
    low_confidence_floor: float = field(default_factory=lambda: _f("LOW_CONFIDENCE_FLOOR", 40))
    soil_saturation_pct: float = field(default_factory=lambda: _f("SOIL_SATURATION_PCT", 80))
    tilt_delta_deg: float = field(default_factory=lambda: _f("TILT_DELTA_DEG", 0.8))

    # --- delivery ----------------------------------------------------------
    sms_provider: str = os.getenv("SMS_PROVIDER", "console")  # console | http | store_forward
    sms_endpoint: str = os.getenv("SMS_ENDPOINT", "")
    sms_api_key: str = os.getenv("SMS_API_KEY", "")
    sms_max_attempts: int = field(default_factory=lambda: _i("SMS_MAX_ATTEMPTS", 4))
    default_languages: str = os.getenv("DEFAULT_LANGUAGES", "en,hi,as")

    # --- ingest ------------------------------------------------------------
    imd_api_base: str = os.getenv("IMD_API_BASE", "")
    imd_api_key: str = os.getenv("IMD_API_KEY", "")
    scheduler_enabled: bool = field(default_factory=lambda: _b("SCHEDULER_ENABLED", True))
    risk_recompute_seconds: int = field(default_factory=lambda: _i("RISK_RECOMPUTE_SECONDS", 900))

    # --- telemetry simulation ----------------------------------------------
    # The sensor fleet is driven by the physics-informed simulator rather than by
    # random numbers. Ticks are what make the console move; each tick writes real
    # SensorReading rows through the same path a LoRa gateway would use.
    simulator_enabled: bool = field(default_factory=lambda: _b("SIMULATOR_ENABLED", True))
    simulator_tick_seconds: int = field(default_factory=lambda: _i("SIMULATOR_TICK_SECONDS", 20))
    # Minutes of simulated time advanced per tick, so a 72-hour scenario is watchable.
    simulator_minutes_per_tick: int = field(default_factory=lambda: _i("SIMULATOR_MINUTES_PER_TICK", 15))
    simulator_seed: int = field(default_factory=lambda: _i("SIMULATOR_SEED", 20260901))

    # --- custom alert rules -------------------------------------------------
    custom_rule_cooldown_minutes: int = field(
        default_factory=lambda: _i("CUSTOM_RULE_COOLDOWN_MIN", 45)
    )

    # How long an externally published model prediction stays authoritative before
    # the local engines resume scoring that zone. Bounded rather than permanent: if
    # the publishing pipeline dies, a stale score must not sit on the console
    # forever claiming to be current.
    model_publish_ttl_minutes: int = field(
        default_factory=lambda: _i("MODEL_PUBLISH_TTL_MIN", 60)
    )

    @property
    def data_confidence(self) -> str:
        """SYNTHETIC until a real ingest is wired. Surfaces straight to the UI labels."""
        return os.getenv("DATA_CONFIDENCE", "SYNTHETIC")


settings = Settings()
