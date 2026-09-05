/**
 * NER Landslide EWS — domain type contracts.
 *
 * These types are deliberately aligned with the field names already published by the
 * offline half of the platform (the data pipeline):
 *
 *   HISTORICAL_EVENT_SCHEMA -> latitude, longitude, state, date, slope_deg, elevation_m,
 *                              rainfall_24h_mm, rainfall_72h_mm, rainfall_7d_mm,
 *                              antecedent_precip_index, soil_moisture_pct,
 *                              landslide_occurred, data_confidence
 *   SENSOR_READING_SCHEMA   -> sensor_id, zone_id, sensor_type, timestamp, value, unit,
 *                              battery_pct, rssi_dbm, expected_interval_s
 *   risk_output_schema()    -> risk_score, risk_level, probability, contributing_factors
 *
 * The UI works in camelCase; `src/services/adapters.ts` maps snake_case API payloads onto
 * these types. If a payload key changes on the server, only the adapters change.
 */

/* ------------------------------------------------------------------ geography */

export type StateCode =
  | "AS" // Assam
  | "AR" // Arunachal Pradesh
  | "MN" // Manipur
  | "ML" // Meghalaya
  | "MZ" // Mizoram
  | "NL" // Nagaland
  | "SK" // Sikkim
  | "TR"; // Tripura

export interface RegionState {
  code: StateCode;
  name: string;
  /** Approximate administrative centroid, used by the map projection. */
  center: LatLng;
}

export interface District {
  id: string;
  name: string;
  stateCode: StateCode;
  stateName?: string;
  /** District-specific 24h rainfall threshold used by the alert engine. */
  alertThreshold24h?: number;
  center: LatLng;
  /** Census-order-of-magnitude population, used for exposure weighting only. */
  population: number;
  /** Terrain descriptor surfaced in GIS filters. */
  terrain: TerrainClass;
}

export type TerrainClass = "HILL" | "STEEP_HILL" | "VALLEY" | "PLATEAU" | "PLAIN";

export interface LatLng {
  lat: number;
  lng: number;
}

/* ------------------------------------------------------------------ risk */

/** Canonical severity ladder. Used for zones, alerts and incidents alike. */
export type RiskLevel = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";

/**
 * Factor keys mirror the trained model's feature names exactly, so
 * `contributing_factors` from the ML service can be rendered without remapping.
 */
export type ContributingFactorKey =
  | "slope_deg"
  | "rainfall_24h_mm"
  | "rainfall_72h_mm"
  | "rainfall_7d_mm"
  | "antecedent_precip_index"
  | "soil_moisture_pct";

export type ContributingFactors = Partial<Record<ContributingFactorKey, number>>;

export interface RiskZone {
  id: string;
  name: string;
  district: string;
  districtId: string;
  stateCode: StateCode;
  center: LatLng;
  /** 0–100. Model output, not a hand-set value. */
  riskScore: number;
  riskLevel: RiskLevel;
  /** 0–1 probability from the classifier. */
  probability: number;
  rainfall24h: number;
  rainfall72h: number;
  rainfall7d: number;
  antecedentPrecipIndex: number;
  soilMoisture: number;
  slope: number;
  elevation: number;
  aspect: number;
  /** 0–100 aggregate health of the sensors feeding this zone. */
  sensorConfidence: number;
  /** NDMA/GSI dispatch tier for this score. Drives who is told, not the map colour. */
  alertTier: string;
  /** Static susceptibility and dynamic trigger indices, 0-1. */
  lsi: number;
  ti: number;
  soilType: string;
  landcover: string;
  /** RULE_ENGINE or ML_MODEL — which produced the score on this row. */
  source: string;
  modelVersion?: string;
  contributingFactors: ContributingFactors;
  nearbyRoads: string[];
  nearbyVillages: string[];
  population: number;
  recommendedAction: string;
  /** Predicted onset window in hours, when the model reports one. */
  expectedWindowHours?: number;
  /** Ring of [lng, lat] pairs. Replace with real GeoJSON polygons from PostGIS. */
  geometry?: GeoPolygon;
  updatedAt: string;
  /** Provenance flag. `SYNTHETIC` must never be presented as an observation. */
  dataConfidence: DataConfidence;
}

export type DataConfidence = "HIGH" | "MEDIUM" | "LOW" | "SYNTHETIC";

export interface GeoPolygon {
  type: "Polygon";
  coordinates: number[][][];
}

export interface RiskSummary {
  regionalRiskScore: number;
  regionalRiskLevel: RiskLevel;
  activeAlerts: number;
  criticalAlerts: number;
  highRiskZones: number;
  totalZones: number;
  sensorsOnline: number;
  sensorsOffline: number;
  sensorsDegraded: number;
  blockedRoads: number;
  atRiskRoads: number;
  reportsPendingVerification: number;
  weatherRiskLevel: RiskLevel;
  populationExposed: number;
  updatedAt: string;
  /** Falls back to the previous cached value if the pipeline stalls. */
  dataFreshnessMinutes: number;
}

export interface RiskTrendPoint {
  date: string;
  riskScore: number;
  rainfall: number;
  alerts: number;
}

/* ------------------------------------------------------------------ sensors */

export type SensorType =
  | "RAIN_GAUGE"
  | "SOIL_MOISTURE"
  | "PIEZOMETER"
  | "TILTMETER"
  | "EXTENSOMETER"
  | "GEOPHONE"
  | "WEATHER_STATION";

export type SensorStatus = "ONLINE" | "DEGRADED" | "OFFLINE";

export interface Sensor {
  id: string; // sensor_id
  name: string;
  zoneId: string; // zone_id
  district: string;
  districtId: string;
  stateCode: StateCode;
  location: LatLng;
  type: SensorType;
  reading: number; // value
  unit: string;
  status: SensorStatus;
  /** 0–100 SensorHealthScorer output. */
  healthScore: number;
  healthSubScores: SensorHealthSubScores;
  batteryPct: number;
  rssiDbm: number;
  expectedIntervalSec: number;
  lastSeen: string; // timestamp
  /** 0–1 share of the zone risk score attributable to this sensor. */
  riskContribution: number;
  maintenanceNote?: string;
  installedOn: string;
  /** LORAWAN | GSM | SATELLITE — how this sensor reaches the gateway. */
  transport: string;
}

/** Weights fixed by the pipeline: completeness .25, validity .25, stability .20, noise .15, comms .15 */
export interface SensorHealthSubScores {
  completeness: number;
  validity: number;
  stability: number;
  noise: number;
  comms: number;
}

export interface SensorReading {
  sensorId: string;
  timestamp: string;
  value: number;
  unit: string;
}

export interface SensorSeries {
  sensorId: string;
  unit: string;
  points: SensorReading[];
}

export interface SensorFleetSummary {
  total: number;
  online: number;
  degraded: number;
  offline: number;
  lowBattery: number;
  commFailures: number;
  meanHealth: number;
  uptimePct: number;
}

/* ------------------------------------------------------------------ alerts */

export type AlertSeverity = "CRITICAL" | "HIGH" | "MODERATE" | "INFORMATION";
export type AlertStatus = "NEW" | "ACKNOWLEDGED" | "IN_PROGRESS" | "RESOLVED";

export type AlertTrigger =
  | "CUSTOM_RULE"
  | "ROAD_BLOCKAGE"
  | "RAINFALL_THRESHOLD"
  | "SOIL_SATURATION"
  | "SLOPE_MOVEMENT"
  | "MODEL_PROBABILITY"
  | "SENSOR_ANOMALY"
  | "FIELD_REPORT"
  | "COMBINED";

export interface Alert {
  id: string;
  severity: AlertSeverity;
  title: string;
  zoneId: string;
  location: string;
  district: string;
  districtId: string;
  stateCode: StateCode;
  center: LatLng;
  issuedAt: string;
  riskScore: number;
  probability: number;
  trigger: AlertTrigger;
  triggerDetail: string;
  expectedWindowHours: number;
  affectedRoads: string[];
  affectedVillages: string[];
  populationAffected: number;
  recommendedAction: string;
  status: AlertStatus;
  acknowledgedBy?: string;
  /** Confidence of the sensors that produced the prediction (0–100). */
  sensorConfidence: number;
  /** NDMA/GSI tier. GREEN sends no message at all. */
  tier: string;
  /** Which built-in rule fired (R1-R7), or the custom rule id. */
  ruleId: string;
  /**
   * HAZARD = the slope may fail. OPERATIONAL = we have lost the ability to tell.
   * These must never be merged: a sensor outage must not overwrite a landslide
   * warning on the same zone.
   */
  alertClass: "HAZARD" | "OPERATIONAL";
  customRuleId?: string;
  /** Every rule that matched this zone, not only the one that won primacy. */
  contributingRules: ContributingRule[];
  lowConfidence: boolean;
  escalationCount: number;
}

export interface ContributingRule {
  ruleId: string;
  trigger: string;
  severity: AlertSeverity;
  detail: string;
  primary: boolean;
}

/* ------------------------------------------------------------------ incidents & field reports */

export type IncidentType =
  | "LANDSLIDE"
  | "ROCKFALL"
  | "CRACK"
  | "ROAD_BLOCKAGE"
  | "SLOPE_MOVEMENT"
  | "FLOOD"
  | "OTHER";

export type ReporterType = "CITIZEN" | "FIELD_OFFICER" | "AUTHORITY";
export type ReportSyncStatus = "PENDING_SYNC" | "SYNCED" | "FAILED";
export type ReportVerification = "PENDING" | "VERIFIED" | "REJECTED";

export interface MediaAttachment {
  id: string;
  name: string;
  kind: "IMAGE" | "VIDEO";
  sizeBytes: number;
  /** Object URL while local; replaced by a storage URL after upload. */
  previewUrl?: string;
  /** The underlying file, present only for attachments picked in this session. */
  file?: File;
}

export interface IncidentReport {
  id: string;
  /** Client-generated key that makes offline replay idempotent. */
  clientId?: string;
  incidentType: IncidentType;
  description: string;
  district: string;
  districtId: string;
  stateCode: StateCode;
  roadOrVillage: string;
  location?: LatLng;
  severity: RiskLevel;
  reporterType: ReporterType;
  reporterName?: string;
  reportedAt: string;
  media: MediaAttachment[];
  syncStatus: ReportSyncStatus;
  verification: ReportVerification;
}

/** A confirmed historical event — the shape the cleaned historical dataset exports. */
export interface HistoricalIncident {
  id: string;
  date: string;
  district: string;
  districtId: string;
  stateCode: StateCode;
  location: string;
  center: LatLng;
  incidentType: IncidentType;
  severity: RiskLevel;
  rainfall24h: number;
  riskScoreAtEvent: number;
  affectedRoad: string;
  affectedPopulation: number;
  responseTimeMinutes: number;
  status: "CLOSED" | "UNDER_REVIEW" | "OPEN";
  /** Whether the platform had raised an alert before the event occurred. */
  predicted: boolean;
  dataConfidence: DataConfidence;
}

/* ------------------------------------------------------------------ weather */

export interface WeatherData {
  districtId: string;
  district: string;
  observedAt: string;
  rainfallNow: number;
  rainfall24h: number;
  rainfall72h: number;
  rainfall7d: number;
  humidity: number;
  temperature: number;
  windKph: number;
  condition: "CLEAR" | "CLOUDY" | "LIGHT_RAIN" | "HEAVY_RAIN" | "THUNDERSTORM";
  weatherRiskLevel: RiskLevel;
  /** Rainfall (mm/24h) above which the alert engine escalates for this district. */
  alertThreshold24h: number;
  forecast: WeatherForecastDay[];
  /** Where the observation came from, e.g. SIMULATED_TELEMETRY or IMD. */
  source: string;
}

export interface WeatherForecastDay {
  date: string;
  rainfallMm: number;
  probabilityPct: number;
  riskLevel: RiskLevel;
  tempMin: number;
  tempMax: number;
}

/* ------------------------------------------------------------------ roads & infrastructure */

export type RoadStatusValue = "OPEN" | "AT_RISK" | "RESTRICTED" | "BLOCKED";

export interface RoadStatus {
  id: string;
  name: string;
  districtId: string;
  district: string;
  status: RoadStatusValue;
  riskLevel: RiskLevel;
  lengthKm: number;
  /** Polyline of [lng, lat] pairs; swap for a real GeoJSON LineString. */
  path: number[][];
  lastUpdated: string;
  note?: string;
}

export type InfrastructureType = "HIGHWAY" | "BRIDGE" | "HOSPITAL" | "SCHOOL" | "VILLAGE";
export type ImportanceLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export interface Infrastructure {
  id: string;
  name: string;
  type: InfrastructureType;
  districtId: string;
  district: string;
  location: LatLng;
  riskLevel: RiskLevel;
  importance: ImportanceLevel;
  /** risk x importance, resolved server-side by the exposure engine. */
  exposure: RiskLevel;
  /** Numeric exposure ranking — which asset gets the one available crew. */
  exposureScore: number;
  populationServed: number;
}

/* ------------------------------------------------------------------ GIS */

/**
 * Layers the operator can toggle.
 *
 * `terrain`, `dem` and `satellite` were removed. The DEM itself is very much alive —
 * it feeds slope and elevation into the risk engine, produces the continuous
 * `spatial_risk` surface, and supplies the report's topographic section. What is gone
 * is the user-facing switch, which answered no operational question.
 */
export type GISLayerId =
  | "risk_heatmap"
  | "spatial_risk"
  | "sensors"
  | "roads"
  | "settlements"
  | "rivers"
  | "infrastructure"
  | "incidents"
  | "rainfall";

export interface GISLayer {
  id: GISLayerId;
  label: string;
  description: string;
  /** Whether the spatial service currently serves this layer. */
  available: boolean;
  defaultOn: boolean;
  /** Where the layer will come from once wired up. */
  sourceHint: string;
  group: "RISK" | "ASSETS";
}

export interface Village {
  id: string;
  name: string;
  districtId: string;
  district: string;
  location: LatLng;
  population: number;
  riskLevel: RiskLevel;
  connectivity: "CONNECTED" | "AT_RISK" | "ISOLATED";
}

/** Derived DEM statistics for the selected district. */
export interface TerrainProfile {
  districtId: string;
  elevationMin: number;
  elevationMax: number;
  elevationMean: number;
  slopeMean: number;
  slopeMax: number;
  aspectDominant: string;
  curvatureMean: number;
  drainageDensity: number;
  ruggednessIndex: number;
  /** Coarse DEM grid (row-major, normalised 0–1) driving the 3D preview. */
  demGrid: number[][];
  source: "SYNTHETIC_DEM" | "CARTODEM" | "SRTM";
}

/* ------------------------------------------------------------------ reports & analytics */

export interface ReportKpi {
  key: string;
  label: string;
  value: string;
  unit?: string;
  deltaPct?: number;
  deltaDirection?: "UP" | "DOWN" | "FLAT";
  /** Whether an increase is a good outcome — drives the delta colour. */
  higherIsBetter?: boolean;
  note?: string;
}

export interface ReportSummary {
  id: string;
  title: string;
  periodLabel: string;
  periodStart: string;
  periodEnd: string;
  generatedAt: string;
  scope: string;
  kpis: ReportKpi[];
  riskTrend: RiskTrendPoint[];
  rainfallVsRisk: { date: string; rainfall: number; riskScore: number; threshold: number }[];
  alertsBySeverity: { severity: AlertSeverity; count: number }[];
  sensorPerformance: { month: string; uptimePct: number; meanHealth: number }[];
  riskCalendar: { date: string; riskLevel: RiskLevel; riskScore: number }[];
  districtComparison: { district: string; riskScore: number; alerts: number; incidents: number }[];
  infrastructureImpact: { type: InfrastructureType; exposed: number; critical: number }[];
  responseMetrics: { label: string; value: number; unit: string }[];
  criticalEvents: { date: string; title: string; district: string; severity: AlertSeverity; note: string }[];
  modelPerformance: ModelPerformance | null;
  /** Ranked infrastructure exposure for this scope. */
  exposureDetail: {
    id: string; name: string; type: string; district: string;
    riskLevel: string; importance: string; exposureScore: number;
  }[];
  /**
   * Ten-year recorded event context from the historical dataset, at state
   * resolution — which is the resolution the source actually has.
   */
  historicalContext: Record<string, unknown>;
  dataConfidence: DataConfidence;
}

/** Mirrors ml/train_risk_model.py evaluation output. */
export interface ModelPerformance {
  selectedModel: string;
  rocAuc: number;
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  featureImportance: { feature: ContributingFactorKey; importance: number }[];
  evaluatedOn: string;
  caveat: string;
}

/* ------------------------------------------------------------------ notifications & UI */

export type NotificationCategory =
  | "CRITICAL_ALERT"
  | "HIGH_RISK"
  | "SENSOR_FAILURE"
  | "ROAD_BLOCKAGE"
  | "CITIZEN_REPORT"
  | "SYSTEM";

export interface AppNotification {
  id: string;
  category: NotificationCategory;
  title: string;
  body: string;
  createdAt: string;
  read: boolean;
  /** In-app route to open when the notification is actioned. */
  href?: string;
}

export type ConnectionState = "ONLINE" | "DEGRADED" | "OFFLINE";

export interface SystemStatus {
  connection: ConnectionState;
  ingestLagSeconds: number;
  modelLastRunAt: string;
  servicesUp: number;
  servicesTotal: number;
  /** Per-service detail, so a DEGRADED banner can say which service and why. */
  services: { name: string; status: string; detail?: string }[];
  dataConfidence: string;
}

export interface ToastMessage {
  id: string;
  tone: "success" | "info" | "warning" | "error";
  title: string;
  body?: string;
}

/** Standard envelope every service returns, so pages handle one shape. */
export interface ServiceResult<T> {
  data: T;
  /**
   * Provenance reported by the backend via `X-Data-Confidence`. This replaced a
   * boolean `demo` flag: what matters operationally is not "is this a demo" but
   * "what is this number made of" — a simulated reading, a historical record and a
   * model output need different amounts of trust, and one boolean cannot say so.
   */
  dataConfidence?: string;
  fetchedAt: string;
}
