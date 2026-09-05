import type { ServiceResult, WeatherData } from "@/types";
import * as A from "./adapters";
import { get, qs, type ScopeFilter } from "./api";

type Raw = Record<string, unknown>;

/**
 * GET /api/weather.
 *
 * With no district the backend returns the one closest to breaching its threshold,
 * because on a regional dashboard that is the only district anybody needs.
 */
export const getWeather = async (scope: ScopeFilter = {}): Promise<ServiceResult<WeatherData>> => {
  const res = await get<Raw>(`/weather${qs(scope)}`);
  return { ...res, data: A.adaptWeather(res.data) };
};

export const getAllWeather = async (): Promise<ServiceResult<WeatherData[]>> => {
  const res = await get<Raw[]>("/weather/all");
  return { ...res, data: res.data.map(A.adaptWeather) };
};
