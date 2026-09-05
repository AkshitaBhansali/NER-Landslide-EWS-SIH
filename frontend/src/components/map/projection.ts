import { NER_BOUNDS } from "@/data/regions";
import type { LatLng } from "@/types";

/**
 * Equirectangular projection over the NER bounding box.
 *
 * Deliberately isolated: the map components only ever call `project()` / `unproject()`,
 * so swapping in MapLibre (or Cesium for the 3D view) means replacing this file and the
 * base-layer renderer, not the layer components — those already consume [lng, lat] pairs
 * in GeoJSON order.
 */

export const VIEW_W = 1000;
export const VIEW_H = Math.round(
  (VIEW_W * (NER_BOUNDS.maxLat - NER_BOUNDS.minLat)) / (NER_BOUNDS.maxLng - NER_BOUNDS.minLng),
);

export interface Viewport {
  minLat: number;
  maxLat: number;
  minLng: number;
  maxLng: number;
}

export const FULL_VIEW: Viewport = { ...NER_BOUNDS };

export function project(point: LatLng, view: Viewport = FULL_VIEW): { x: number; y: number } {
  const x = ((point.lng - view.minLng) / (view.maxLng - view.minLng)) * VIEW_W;
  const y = VIEW_H - ((point.lat - view.minLat) / (view.maxLat - view.minLat)) * VIEW_H;
  return { x, y };
}

/** GeoJSON position order is [lng, lat]. */
export const projectCoord = ([lng, lat]: number[], view: Viewport = FULL_VIEW) =>
  project({ lat, lng }, view);

export const pathFromCoords = (coords: number[][], view: Viewport = FULL_VIEW): string =>
  coords
    .map((c, i) => {
      const p = projectCoord(c, view);
      return `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    })
    .join(" ");

export const polygonPoints = (ring: number[][], view: Viewport = FULL_VIEW): string =>
  ring.map((c) => {
    const p = projectCoord(c, view);
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(" ");

/** Bounding view around a set of points, with padding, for "zoom to district". */
export function viewportFor(points: LatLng[], padDeg = 0.45): Viewport {
  if (!points.length) return FULL_VIEW;
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  return {
    minLat: Math.min(...lats) - padDeg,
    maxLat: Math.max(...lats) + padDeg,
    minLng: Math.min(...lngs) - padDeg,
    maxLng: Math.max(...lngs) + padDeg,
  };
}
