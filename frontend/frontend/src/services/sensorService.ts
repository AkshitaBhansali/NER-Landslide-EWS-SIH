import type { Sensor, SensorFleetSummary, SensorReading, ServiceResult } from "@/types";
import * as A from "./adapters";
import { get, post, qs, type ScopeFilter } from "./api";

type Raw = Record<string, unknown>;

/** GET /api/sensors — worst health first. */
export const getSensors = async (
  scope: ScopeFilter = {},
  filters: { status?: string; sensor_type?: string; zone_id?: string } = {},
): Promise<ServiceResult<Sensor[]>> => {
  const res = await get<Raw[]>(`/sensors${qs(scope, filters)}`);
  return { ...res, data: res.data.map(A.adaptSensor) };
};

export const getSensorById = async (id: string): Promise<ServiceResult<Sensor>> => {
  const res = await get<Raw>(`/sensors/${encodeURIComponent(id)}`);
  return { ...res, data: A.adaptSensor(res.data) };
};

/** GET /api/sensors/:id/readings */
export const getSensorReadings = async (
  id: string,
  hours = 24,
): Promise<ServiceResult<SensorReading[]>> => {
  const res = await get<Raw[]>(`/sensors/${encodeURIComponent(id)}/readings?hours=${hours}`);
  return { ...res, data: res.data.map(A.adaptSensorReading) };
};

export const getSensorsForZone = (zoneId: string) => getSensors({}, { zone_id: zoneId });

export const getSensorSummary = async (
  scope: ScopeFilter = {},
): Promise<ServiceResult<SensorFleetSummary>> => {
  const res = await get<Raw>(`/sensors/summary${qs(scope)}`);
  return { ...res, data: A.adaptFleetSummary(res.data) };
};

/* ------------------------------------------------------------------ scenarios */

export interface Scenario {
  key: string;
  label: string;
  summary: string;
  chain: string[];
  expected: string;
  active: boolean;
}

export interface SimulationState {
  scenario: string;
  scenarioLabel: string;
  chain: string[];
  expected: string;
  scopeId: string;
  tick: number;
  simulatedClock: string;
  minutesPerTick: number;
  tickSeconds: number;
  running: boolean;
  offlineSensors: string[];
  lastCycle: Record<string, unknown>;
}

const adaptState = (raw: Raw): SimulationState => ({
  scenario: String(raw.scenario ?? "NORMAL"),
  scenarioLabel: String(raw.scenario_label ?? "Normal"),
  chain: (raw.chain as string[]) ?? [],
  expected: String(raw.expected ?? ""),
  scopeId: String(raw.scope_id ?? "ALL"),
  tick: Number(raw.tick ?? 0),
  simulatedClock: String(raw.simulated_clock ?? ""),
  minutesPerTick: Number(raw.minutes_per_tick ?? 15),
  tickSeconds: Number(raw.tick_seconds ?? 20),
  running: raw.running === true,
  offlineSensors: (raw.offline_sensors as string[]) ?? [],
  lastCycle: (raw.last_cycle as Record<string, unknown>) ?? {},
});

export const getScenarios = async (): Promise<ServiceResult<Scenario[]>> => {
  const res = await get<Raw[]>("/simulation/scenarios");
  return {
    ...res,
    data: res.data.map((s) => ({
      key: String(s.key), label: String(s.label), summary: String(s.summary),
      chain: (s.chain as string[]) ?? [], expected: String(s.expected),
      active: s.active === true,
    })),
  };
};

export const getSimulationState = async (): Promise<ServiceResult<SimulationState>> => {
  const res = await get<Raw>("/simulation/state");
  return { ...res, data: adaptState(res.data) };
};

/**
 * Apply a scenario. This perturbs sensor inputs and lets the risk and alert
 * engines reach their own conclusions — it never writes an alert directly.
 */
export const applyScenario = async (scenario: string, scopeId = "ALL") => {
  const res = await post<Raw>("/simulation/apply", { scenario, scope_id: scopeId });
  return { ...res, data: adaptState(res.data) };
};

export const tickSimulation = async () => {
  const res = await post<Raw>("/simulation/tick");
  return { ...res, data: adaptState(res.data) };
};

export const resetSimulation = async () => {
  const res = await post<Raw>("/simulation/reset");
  return { ...res, data: adaptState(res.data) };
};
