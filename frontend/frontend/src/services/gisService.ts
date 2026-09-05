import type { GISLayer, Infrastructure, RoadStatus, ServiceResult, TerrainProfile, Village } from "@/types";
import * as A from "./adapters";
import { get, qs, type ScopeFilter } from "./api";

type Raw = Record<string, unknown>;

export interface FeatureCollection {
  type: "FeatureCollection";
  features: GeoFeature[];
  properties?: Record<string, unknown>;
}

export interface GeoFeature {
  type: "Feature";
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown>;
}

/**
 * GET /api/gis/layers — the operational layer registry.
 *
 * DEM / terrain shading / satellite imagery are intentionally absent. The DEM is
 * still loaded and used server-side for slope, elevation, the spatial risk surface
 * and the report's topographic section; what was removed is the toggle, because an
 * operator managing an active event does not need a hillshade basemap.
 */
export const getLayers = async (): Promise<ServiceResult<GISLayer[]>> => {
  const res = await get<Raw[]>("/gis/layers");
  return {
    ...res,
    data: res.data.map((l) => ({
      id: String(l.id) as GISLayer["id"],
      label: String(l.label),
      description: String(l.description),
      available: l.available === true,
      defaultOn: l.default_on === true,
      sourceHint: String(l.source_hint ?? ""),
      group: String(l.group ?? "RISK") as GISLayer["group"],
    })),
  };
};

export const getLayer = (
  layerId: string,
  scope: ScopeFilter = {},
  timestep?: number,
): Promise<ServiceResult<FeatureCollection>> =>
  get<FeatureCollection>(`/gis/layers/${encodeURIComponent(layerId)}${qs(scope, { timestep })}`);

/** Corridor headline state: bounds, elevation range, exposure, ranked priorities. */
export const getCorridor = (timestep = 0) => get<Raw>(`/gis/corridor?timestep=${timestep}`);

/** Exposure = risk x importance. Which asset gets the one available crew. */
export const getExposure = (scope: ScopeFilter = {}, timestep = 0) =>
  get<Raw>(`/gis/exposure${qs(scope, { timestep })}`);

/**
 * Everything known about one point — what a map click resolves to.
 *
 * Risk and its inputs, the sensors reporting it, the DEM-derived terrain and the
 * assets standing in it, in one response. A map that shows a coloured polygon and
 * nothing else makes the operator go and look the area up somewhere else.
 */
export const getPointContext = (lat: number, lng: number, radiusKm = 3, timestep = 0) =>
  get<Raw>(`/gis/context?lat=${lat}&lng=${lng}&radius_km=${radiusKm}&timestep=${timestep}`);

/** DEM-derived terrain statistics. Used for context panels, not as a map layer. */
export const getTerrain = async (scope: ScopeFilter = {}): Promise<ServiceResult<TerrainProfile>> => {
  const res = await get<Raw>(`/gis/terrain${qs(scope)}`);
  const r = res.data;
  return {
    ...res,
    data: {
      districtId: String(r.district_id ?? ""),
      elevationMin: Number(r.elevation_min ?? 0),
      elevationMax: Number(r.elevation_max ?? 0),
      elevationMean: Number(r.elevation_mean ?? 0),
      slopeMean: Number(r.slope_mean ?? 0),
      slopeMax: Number(r.slope_max ?? 0),
      aspectDominant: String(r.aspect_dominant ?? "S"),
      curvatureMean: Number(r.curvature_mean ?? 0),
      drainageDensity: Number(r.drainage_density ?? 0),
      ruggednessIndex: Number(r.ruggedness_index ?? 0),
      demGrid: (r.dem_grid as number[][]) ?? [],
      source: String(r.source ?? "MODEL_DERIVED") as TerrainProfile["source"],
    },
  };
};

export const getRoads = async (scope: ScopeFilter = {}): Promise<ServiceResult<RoadStatus[]>> => {
  const res = await get<Raw[]>(`/roads${qs(scope)}`);
  return { ...res, data: res.data.map(A.adaptRoad) };
};

export const getVillages = async (scope: ScopeFilter = {}): Promise<ServiceResult<Village[]>> => {
  const res = await get<Raw[]>(`/villages${qs(scope)}`);
  return { ...res, data: res.data.map(A.adaptVillage) };
};

export const getInfrastructure = async (
  scope: ScopeFilter = {},
): Promise<ServiceResult<Infrastructure[]>> => {
  const res = await get<Raw[]>(`/gis/infrastructure${qs(scope)}`);
  return { ...res, data: res.data.map(A.adaptInfrastructure) };
};
