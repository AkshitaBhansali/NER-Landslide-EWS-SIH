import type { SensorType } from "@/types";

/**
 * Display labels and units for each instrument class.
 *
 * Mirrors `app/core/sensor_health.py:LABELS/UNITS` on the backend. Kept client-side
 * because it is presentation, not data: the API sends the enum and the unit it
 * actually measured in, and this only decides how that reads on screen.
 */
export const SENSOR_TYPE_LABEL: Record<SensorType, string> = {
  RAIN_GAUGE: "Rain gauge",
  SOIL_MOISTURE: "Soil moisture",
  PIEZOMETER: "Piezometer",
  TILTMETER: "Tiltmeter",
  EXTENSOMETER: "Extensometer",
  GEOPHONE: "Geophone",
  WEATHER_STATION: "Weather station",
};

export const sensorTypeLabel = (type: SensorType): string =>
  SENSOR_TYPE_LABEL[type] ?? String(type).replace(/_/g, " ").toLowerCase();
