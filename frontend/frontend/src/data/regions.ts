import type { District, RegionState } from "@/types";

/**
 * Reference geography for the eight NER states.
 *
 * Coordinates are approximate district-headquarters positions, adequate for the
 * prototype projection. They are replaced wholesale once the GIS service serves
 * real district boundaries from PostGIS (`GET /api/gis/districts`).
 */

export const NER_BOUNDS = {
  minLat: 22.0,
  maxLat: 28.6,
  minLng: 87.9,
  maxLng: 97.4,
};

export const STATES: RegionState[] = [
  { code: "AS", name: "Assam", center: { lat: 26.2, lng: 92.9 } },
  { code: "AR", name: "Arunachal Pradesh", center: { lat: 28.0, lng: 94.7 } },
  { code: "MN", name: "Manipur", center: { lat: 24.7, lng: 93.9 } },
  { code: "ML", name: "Meghalaya", center: { lat: 25.5, lng: 91.4 } },
  { code: "MZ", name: "Mizoram", center: { lat: 23.4, lng: 92.8 } },
  { code: "NL", name: "Nagaland", center: { lat: 26.1, lng: 94.4 } },
  { code: "SK", name: "Sikkim", center: { lat: 27.5, lng: 88.5 } },
  { code: "TR", name: "Tripura", center: { lat: 23.8, lng: 91.6 } },
];

export const DISTRICTS: District[] = [
  // Assam
  { id: "as-dima-hasao", name: "Dima Hasao", stateCode: "AS", center: { lat: 25.35, lng: 93.03 }, population: 214102, terrain: "STEEP_HILL" },
  { id: "as-karbi-anglong", name: "Karbi Anglong", stateCode: "AS", center: { lat: 25.95, lng: 93.42 }, population: 660955, terrain: "HILL" },
  { id: "as-cachar", name: "Cachar", stateCode: "AS", center: { lat: 24.83, lng: 92.78 }, population: 1736617, terrain: "VALLEY" },
  { id: "as-hailakandi", name: "Hailakandi", stateCode: "AS", center: { lat: 24.68, lng: 92.56 }, population: 659296, terrain: "VALLEY" },
  { id: "as-kamrup-metro", name: "Kamrup Metropolitan", stateCode: "AS", center: { lat: 26.14, lng: 91.74 }, population: 1253938, terrain: "PLAIN" },
  { id: "as-goalpara", name: "Goalpara", stateCode: "AS", center: { lat: 26.17, lng: 90.62 }, population: 1008183, terrain: "PLAIN" },
  // Arunachal Pradesh
  { id: "ar-tawang", name: "Tawang", stateCode: "AR", center: { lat: 27.59, lng: 91.87 }, population: 49977, terrain: "STEEP_HILL" },
  { id: "ar-papum-pare", name: "Papum Pare", stateCode: "AR", center: { lat: 27.1, lng: 93.62 }, population: 176573, terrain: "HILL" },
  { id: "ar-lower-subansiri", name: "Lower Subansiri", stateCode: "AR", center: { lat: 27.62, lng: 93.83 }, population: 83030, terrain: "STEEP_HILL" },
  { id: "ar-dibang-valley", name: "Dibang Valley", stateCode: "AR", center: { lat: 28.65, lng: 95.9 }, population: 8004, terrain: "STEEP_HILL" },
  // Manipur
  { id: "mn-imphal-west", name: "Imphal West", stateCode: "MN", center: { lat: 24.81, lng: 93.9 }, population: 517992, terrain: "VALLEY" },
  { id: "mn-churachandpur", name: "Churachandpur", stateCode: "MN", center: { lat: 24.33, lng: 93.68 }, population: 271274, terrain: "HILL" },
  { id: "mn-senapati", name: "Senapati", stateCode: "MN", center: { lat: 25.27, lng: 94.02 }, population: 354772, terrain: "STEEP_HILL" },
  { id: "mn-noney", name: "Noney", stateCode: "MN", center: { lat: 24.83, lng: 93.53 }, population: 47217, terrain: "STEEP_HILL" },
  // Meghalaya
  { id: "ml-east-khasi-hills", name: "East Khasi Hills", stateCode: "ML", center: { lat: 25.57, lng: 91.88 }, population: 825922, terrain: "PLATEAU" },
  { id: "ml-ri-bhoi", name: "Ri-Bhoi", stateCode: "ML", center: { lat: 25.9, lng: 91.88 }, population: 258840, terrain: "HILL" },
  { id: "ml-west-jaintia-hills", name: "West Jaintia Hills", stateCode: "ML", center: { lat: 25.45, lng: 92.2 }, population: 270352, terrain: "PLATEAU" },
  { id: "ml-south-garo-hills", name: "South Garo Hills", stateCode: "ML", center: { lat: 25.32, lng: 90.62 }, population: 142334, terrain: "HILL" },
  // Mizoram
  { id: "mz-aizawl", name: "Aizawl", stateCode: "MZ", center: { lat: 23.73, lng: 92.72 }, population: 400309, terrain: "STEEP_HILL" },
  { id: "mz-lunglei", name: "Lunglei", stateCode: "MZ", center: { lat: 22.88, lng: 92.73 }, population: 161428, terrain: "STEEP_HILL" },
  { id: "mz-serchhip", name: "Serchhip", stateCode: "MZ", center: { lat: 23.3, lng: 92.85 }, population: 64937, terrain: "HILL" },
  // Nagaland
  { id: "nl-kohima", name: "Kohima", stateCode: "NL", center: { lat: 25.67, lng: 94.11 }, population: 267988, terrain: "STEEP_HILL" },
  { id: "nl-dimapur", name: "Dimapur", stateCode: "NL", center: { lat: 25.9, lng: 93.73 }, population: 378811, terrain: "PLAIN" },
  { id: "nl-phek", name: "Phek", stateCode: "NL", center: { lat: 25.67, lng: 94.47 }, population: 163418, terrain: "HILL" },
  // Sikkim
  { id: "sk-gangtok", name: "Gangtok", stateCode: "SK", center: { lat: 27.33, lng: 88.61 }, population: 283583, terrain: "STEEP_HILL" },
  { id: "sk-mangan", name: "Mangan", stateCode: "SK", center: { lat: 27.51, lng: 88.53 }, population: 43709, terrain: "STEEP_HILL" },
  { id: "sk-namchi", name: "Namchi", stateCode: "SK", center: { lat: 27.17, lng: 88.36 }, population: 146742, terrain: "HILL" },
  // Tripura
  { id: "tr-west-tripura", name: "West Tripura", stateCode: "TR", center: { lat: 23.84, lng: 91.28 }, population: 917534, terrain: "PLAIN" },
  { id: "tr-dhalai", name: "Dhalai", stateCode: "TR", center: { lat: 23.93, lng: 91.83 }, population: 378230, terrain: "HILL" },
  { id: "tr-south-tripura", name: "South Tripura", stateCode: "TR", center: { lat: 23.31, lng: 91.48 }, population: 430751, terrain: "HILL" },
];

export const stateByCode = (code: string): RegionState | undefined =>
  STATES.find((s) => s.code === code);

export const districtsForState = (code: string): District[] =>
  DISTRICTS.filter((d) => d.stateCode === code);

export const districtById = (id: string): District | undefined =>
  DISTRICTS.find((d) => d.id === id);

/** Terrain classes ordered by baseline landslide susceptibility. */
export const TERRAIN_RISK_WEIGHT: Record<District["terrain"], number> = {
  STEEP_HILL: 1,
  HILL: 0.78,
  PLATEAU: 0.62,
  VALLEY: 0.45,
  PLAIN: 0.2,
};
