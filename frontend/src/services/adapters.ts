/**
 * snake_case (backend) -> camelCase (UI types).
 *
 * The only place in the frontend that knows backend field names. Field names on
 * the left mirror `app/serializers.py` exactly; if a payload key changes on the
 * server, this file is the whole blast radius.
 *
 * Adapters are defensive about missing fields rather than trusting the payload:
 * an older backend, a partial response over a bad link, or a field that has not
 * been populated yet must degrade to a sensible value, not to `undefined` rendered
 * as "NaN" on an operations screen.
 */
import type {
  Alert,
  AlertSeverity,
  AlertStatus,
  AlertTrigger,
  ContributingFactors,
  HistoricalIncident,
  IncidentReport,
  IncidentType,
  Infrastructure,
  RiskLevel,
  RiskZone,
  RoadStatus,
  Sensor,
  SensorFleetSummary,
  SensorReading,
  SensorStatus,
  SensorType,
  StateCode,
  Village,
  WeatherData,
} from "@/types";

const num = (v: unknown, fallback = 0): number =>
  typeof v === "number" && Number.isFinite(v) ? v : fallback;
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

export const normaliseRiskLevel = (value: unknown): RiskLevel => {
  const v = str(value).toUpperCase();
  if (v === "CRITICAL" || v === "SEVERE") return "CRITICAL";
  if (v === "HIGH") return "HIGH";
  if (v === "MODERATE" || v === "MEDIUM") return "MODERATE";
  return "LOW";
};

const latLng = (v: unknown) => {
  const o = (v ?? {}) as { lat?: number; lng?: number };
  return { lat: num(o.lat), lng: num(o.lng) };
};

/* ------------------------------------------------------------------ risk */

export function adaptRiskZone(raw: Record<string, unknown>): RiskZone {
  return {
    id: str(raw.id),
    name: str(raw.name, "Unnamed zone"),
    district: str(raw.district),
    districtId: str(raw.district_id),
    stateCode: str(raw.state_code) as StateCode,
    center: latLng(raw.center),
    riskScore: num(raw.risk_score),
    riskLevel: normaliseRiskLevel(raw.risk_level),
    alertTier: str(raw.alert_tier, "GREEN"),
    probability: num(raw.probability),
    lsi: num(raw.lsi),
    ti: num(raw.ti),
    rainfall24h: num(raw.rainfall_24h_mm),
    rainfall72h: num(raw.rainfall_72h_mm),
    rainfall7d: num(raw.rainfall_7d_mm),
    antecedentPrecipIndex: num(raw.antecedent_precip_index),
    soilMoisture: num(raw.soil_moisture_pct),
    slope: num(raw.slope_deg),
    elevation: num(raw.elevation_m),
    aspect: num(raw.aspect_deg),
    soilType: str(raw.soil_type),
    landcover: str(raw.landcover),
    sensorConfidence: num(raw.sensor_confidence, 100),
    contributingFactors: (raw.contributing_factors ?? {}) as ContributingFactors,
    nearbyRoads: [],
    nearbyVillages: [],
    population: num(raw.population),
    recommendedAction: str(raw.recommended_action),
    expectedWindowHours: raw.expected_window_hours == null ? undefined : num(raw.expected_window_hours),
    geometry: (raw.geometry ?? undefined) as RiskZone["geometry"],
    source: str(raw.source, "RULE_ENGINE"),
    modelVersion: raw.model_version == null ? undefined : str(raw.model_version),
    updatedAt: str(raw.updated_at, new Date().toISOString()),
    dataConfidence: str(raw.data_confidence, "SYNTHETIC") as RiskZone["dataConfidence"],
  };
}

export function adaptRiskSummary(raw: Record<string, unknown>) {
  return {
    regionalRiskScore: num(raw.regional_risk_score),
    regionalRiskLevel: normaliseRiskLevel(raw.regional_risk_level),
    activeAlerts: num(raw.active_alerts),
    criticalAlerts: num(raw.critical_alerts),
    highRiskZones: num(raw.high_risk_zones),
    totalZones: num(raw.total_zones),
    sensorsOnline: num(raw.sensors_online),
    sensorsDegraded: num(raw.sensors_degraded),
    sensorsOffline: num(raw.sensors_offline),
    blockedRoads: num(raw.blocked_roads),
    atRiskRoads: num(raw.at_risk_roads),
    reportsPendingVerification: num(raw.reports_pending_verification),
    weatherRiskLevel: normaliseRiskLevel(raw.weather_risk_level),
    populationExposed: num(raw.population_exposed),
    updatedAt: str(raw.updated_at, new Date().toISOString()),
    dataFreshnessMinutes: num(raw.data_freshness_minutes),
    dataConfidence: str(raw.data_confidence, "SYNTHETIC"),
  };
}

export const adaptTrendPoint = (raw: Record<string, unknown>) => ({
  date: str(raw.date),
  riskScore: num(raw.risk_score),
  rainfall: num(raw.rainfall),
  alerts: num(raw.alerts),
});

export const adaptPipeline = (raw: Record<string, unknown>) => ({
  sensorsReporting: num(raw.sensors_reporting),
  sensorsTotal: num(raw.sensors_total),
  meanSensorHealth: num(raw.mean_sensor_health),
  zonesScored: num(raw.zones_scored),
  meanConfidence: num(raw.mean_confidence),
  eventsPrecededByAlert: num(raw.events_preceded_by_alert),
});

/* ------------------------------------------------------------------ sensors */

export function adaptSensor(raw: Record<string, unknown>): Sensor {
  const sub = (raw.health_sub_scores ?? {}) as Record<string, number>;
  return {
    id: str(raw.sensor_id ?? raw.id),
    name: str(raw.name),
    zoneId: str(raw.zone_id),
    district: str(raw.district),
    districtId: str(raw.district_id),
    stateCode: str(raw.state_code) as StateCode,
    location: latLng(raw.location),
    type: str(raw.sensor_type) as SensorType,
    reading: num(raw.reading),
    unit: str(raw.unit),
    status: str(raw.status, "OFFLINE") as SensorStatus,
    healthScore: num(raw.health_score),
    healthSubScores: {
      completeness: num(sub.completeness),
      validity: num(sub.validity),
      stability: num(sub.stability),
      noise: num(sub.noise),
      comms: num(sub.comms),
    },
    batteryPct: num(raw.battery_pct),
    rssiDbm: num(raw.rssi_dbm, -120),
    expectedIntervalSec: num(raw.expected_interval_s, 900),
    lastSeen: str(raw.last_seen, new Date().toISOString()),
    riskContribution: num(raw.risk_contribution),
    maintenanceNote: raw.maintenance_note == null ? undefined : str(raw.maintenance_note),
    installedOn: str(raw.installed_on),
    transport: str(raw.transport, "LORAWAN"),
  };
}

export const adaptSensorReading = (raw: Record<string, unknown>): SensorReading => ({
  sensorId: str(raw.sensor_id),
  timestamp: str(raw.timestamp),
  value: num(raw.value),
  unit: str(raw.unit),
});

export const adaptFleetSummary = (raw: Record<string, unknown>): SensorFleetSummary => ({
  total: num(raw.total),
  online: num(raw.online),
  degraded: num(raw.degraded),
  offline: num(raw.offline),
  lowBattery: num(raw.low_battery),
  commFailures: num(raw.comm_failures),
  meanHealth: num(raw.mean_health),
  uptimePct: num(raw.uptime_pct),
});

/* ------------------------------------------------------------------ alerts */

export function adaptAlert(raw: Record<string, unknown>): Alert {
  return {
    id: str(raw.id),
    severity: str(raw.severity, "INFORMATION") as AlertSeverity,
    tier: str(raw.tier, "GREEN"),
    title: str(raw.title),
    zoneId: str(raw.zone_id),
    location: str(raw.location),
    district: str(raw.district),
    districtId: str(raw.district_id),
    stateCode: str(raw.state_code) as StateCode,
    center: latLng(raw.center),
    issuedAt: str(raw.issued_at),
    riskScore: num(raw.risk_score),
    probability: num(raw.probability),
    trigger: str(raw.trigger, "COMBINED") as AlertTrigger,
    triggerDetail: str(raw.trigger_detail),
    ruleId: str(raw.rule_id),
    alertClass: str(raw.alert_class, "HAZARD") as Alert["alertClass"],
    customRuleId: raw.custom_rule_id == null ? undefined : str(raw.custom_rule_id),
    contributingRules: arr<Record<string, unknown>>(raw.contributing_rules).map((c) => ({
      ruleId: str(c.rule_id),
      trigger: str(c.trigger),
      severity: str(c.severity) as AlertSeverity,
      detail: str(c.detail),
      primary: c.primary === true,
    })),
    expectedWindowHours: num(raw.expected_window_hours, 24),
    affectedRoads: arr<string>(raw.affected_roads),
    affectedVillages: arr<string>(raw.affected_villages),
    populationAffected: num(raw.population_affected),
    recommendedAction: str(raw.recommended_action),
    status: str(raw.status, "NEW") as AlertStatus,
    acknowledgedBy: raw.acknowledged_by == null ? undefined : str(raw.acknowledged_by),
    sensorConfidence: num(raw.sensor_confidence, 100),
    lowConfidence: raw.low_confidence === true,
    escalationCount: num(raw.escalation_count),
  };
}

/* ------------------------------------------------------------------ incidents */

export const adaptIncident = (raw: Record<string, unknown>): HistoricalIncident => ({
  id: str(raw.id),
  date: str(raw.date),
  district: str(raw.district),
  districtId: str(raw.district_id),
  stateCode: str(raw.state_code) as StateCode,
  location: str(raw.location),
  center: latLng(raw.center),
  incidentType: str(raw.incident_type, "OTHER") as IncidentType,
  severity: normaliseRiskLevel(raw.severity),
  rainfall24h: num(raw.rainfall_24h_mm),
  riskScoreAtEvent: num(raw.risk_score_at_event),
  affectedRoad: str(raw.affected_road),
  affectedPopulation: num(raw.affected_population),
  responseTimeMinutes: num(raw.response_time_minutes),
  status: str(raw.status, "CLOSED") as HistoricalIncident["status"],
  predicted: raw.predicted === true,
  dataConfidence: str(raw.data_confidence, "SYNTHETIC") as HistoricalIncident["dataConfidence"],
});

export const adaptFieldReport = (raw: Record<string, unknown>): IncidentReport => ({
  id: str(raw.id),
  clientId: raw.client_id == null ? undefined : str(raw.client_id),
  incidentType: str(raw.incident_type, "OTHER") as IncidentType,
  description: str(raw.description),
  district: str(raw.district),
  districtId: str(raw.district_id),
  stateCode: str(raw.state_code) as StateCode,
  roadOrVillage: str(raw.road_or_village),
  location: raw.location ? latLng(raw.location) : undefined,
  severity: normaliseRiskLevel(raw.severity),
  reporterType: str(raw.reporter_type, "CITIZEN") as IncidentReport["reporterType"],
  reporterName: raw.reporter_name == null ? undefined : str(raw.reporter_name),
  reportedAt: str(raw.reported_at),
  media: arr<Record<string, unknown>>(raw.media).map((m) => ({
    id: str(m.id),
    name: str(m.filename),
    kind: str(m.kind, "IMAGE") as "IMAGE" | "VIDEO",
    sizeBytes: num(m.size_bytes),
    previewUrl: str(m.url) || undefined,
  })),
  syncStatus: str(raw.sync_status, "SYNCED") as IncidentReport["syncStatus"],
  verification: str(raw.verification, "PENDING") as IncidentReport["verification"],
});

/* ------------------------------------------------------------------ assets */

export const adaptRoad = (raw: Record<string, unknown>): RoadStatus => ({
  id: str(raw.id),
  name: str(raw.name),
  districtId: str(raw.district_id),
  district: str(raw.district),
  status: str(raw.status, "OPEN") as RoadStatus["status"],
  riskLevel: normaliseRiskLevel(raw.risk_level),
  lengthKm: num(raw.length_km),
  path: arr<number[]>(raw.path),
  lastUpdated: str(raw.last_updated),
  note: raw.note == null ? undefined : str(raw.note),
});

export const adaptVillage = (raw: Record<string, unknown>): Village => ({
  id: str(raw.id),
  name: str(raw.name),
  districtId: str(raw.district_id),
  district: str(raw.district),
  location: latLng(raw.location),
  population: num(raw.population),
  riskLevel: normaliseRiskLevel(raw.risk_level),
  connectivity: str(raw.connectivity, "CONNECTED") as Village["connectivity"],
});

export const adaptInfrastructure = (raw: Record<string, unknown>): Infrastructure => ({
  id: str(raw.id),
  name: str(raw.name),
  type: str(raw.type, "VILLAGE") as Infrastructure["type"],
  districtId: str(raw.district_id),
  district: str(raw.district),
  location: latLng(raw.location),
  riskLevel: normaliseRiskLevel(raw.risk_level),
  importance: str(raw.importance, "MEDIUM") as Infrastructure["importance"],
  exposure: normaliseRiskLevel(raw.exposure),
  exposureScore: num(raw.exposure_score),
  populationServed: num(raw.population_served),
});

/* ------------------------------------------------------------------ weather */

export const adaptWeather = (raw: Record<string, unknown>): WeatherData => ({
  districtId: str(raw.district_id),
  district: str(raw.district),
  observedAt: str(raw.observed_at),
  rainfallNow: num(raw.rainfall_now),
  rainfall24h: num(raw.rainfall_24h),
  rainfall72h: num(raw.rainfall_72h),
  rainfall7d: num(raw.rainfall_7d),
  humidity: num(raw.humidity),
  temperature: num(raw.temperature),
  windKph: num(raw.wind_kph),
  condition: str(raw.condition, "CLEAR") as WeatherData["condition"],
  weatherRiskLevel: normaliseRiskLevel(raw.weather_risk_level),
  alertThreshold24h: num(raw.alert_threshold_24h, 95),
  forecast: arr<Record<string, unknown>>(raw.forecast).map((f) => ({
    date: str(f.date),
    rainfallMm: num(f.rainfall_mm),
    probabilityPct: num(f.probability_pct),
    riskLevel: normaliseRiskLevel(f.risk_level),
    tempMin: num(f.temp_min),
    tempMax: num(f.temp_max),
  })),
  source: str(raw.source, "SIMULATED_TELEMETRY"),
});

export const adaptNotification = (raw: Record<string, unknown>) => ({
  id: str(raw.id),
  category: str(raw.category, "SYSTEM") as
    | "CRITICAL_ALERT" | "HIGH_RISK" | "SENSOR_FAILURE"
    | "ROAD_BLOCKAGE" | "CITIZEN_REPORT" | "SYSTEM",
  title: str(raw.title),
  body: str(raw.body),
  createdAt: str(raw.created_at),
  read: raw.read === true,
  href: raw.href == null ? undefined : str(raw.href),
});

/* ------------------------------------------------------------------ districts */

export const adaptDistrict = (raw: Record<string, unknown>) => ({
  id: str(raw.id),
  name: str(raw.name),
  stateCode: str(raw.state_code) as StateCode,
  stateName: str(raw.state_name),
  center: latLng(raw.center),
  population: num(raw.population),
  terrain: str(raw.terrain, "HILL") as
    "HILL" | "STEEP_HILL" | "VALLEY" | "PLATEAU" | "PLAIN",
  alertThreshold24h: num(raw.alert_threshold_24h, 95),
});
