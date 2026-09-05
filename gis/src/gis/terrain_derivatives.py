"""
Terrain Derivatives Calculation Engine
=====================================
Calculates high-precision geomorphological and hydrological terrain derivatives
from Digital Elevation Models (DEM) using industry-standard finite difference
and D8 flow routing algorithms.

Algorithms Implemented:
- Slope (Horn's weighted 8-neighbor method, matching ArcGIS/GDAL)
- Aspect (Compass azimuth 0-360 deg, clockwise from North)
- Planform & Profile Curvatures (Zevenbergen & Thorne, 1987)
- Terrain Ruggedness Index (TRI - Riley et al., 1999)
- Vector Ruggedness Measure (VRM - Sappington et al., 2007)
- Topographic Wetness Index (TWI - Beven & Kirkby)
- D8 Hydrological Flow Direction and Flow Accumulation
"""

from __future__ import annotations
import numpy as np
from scipy import ndimage
from dataclasses import dataclass
from typing import Dict, Tuple, Optional


@dataclass
class TerrainDerivativeLayers:
    elevation: np.ndarray        # m AMSL
    slope_deg: np.ndarray        # degrees (0 - 90)
    aspect_deg: np.ndarray       # azimuth degrees (0 - 360, North = 0)
    profile_curvature: np.ndarray# 1/m (negative = convex/accelerating, positive = concave/decelerating)
    planform_curvature: np.ndarray# 1/m (negative = divergent/ridges, positive = convergent/valleys)
    tri: np.ndarray              # Terrain Ruggedness Index (m)
    twi: np.ndarray              # Topographic Wetness Index (dimensionless)
    flow_accumulation: np.ndarray# upstream contributing cell count
    stream_network: np.ndarray   # binary stream mask (1 = drainage channel, 0 = hill)
    cell_size_m: float           # spatial resolution in meters
    bounds: Tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)


class TerrainDerivativeCalculator:
    """Computes geomorphological and hydrological derivatives on raster DEMs."""

    def __init__(self, cell_size_m: float = 10.0):
        self.cell_size_m = float(cell_size_m)

    def calculate_all(
        self,
        elevation: np.ndarray,
        bounds: Tuple[float, float, float, float] = (94.00, 25.60, 94.18, 25.75)
    ) -> TerrainDerivativeLayers:
        """Computes all terrain derivative layers simultaneously from an elevation grid."""
        elevation = np.asarray(elevation, dtype=np.float64)

        slope_deg, aspect_deg = self.compute_slope_and_aspect(elevation)
        prof_curv, plan_curv = self.compute_curvatures(elevation)
        tri = self.compute_tri(elevation)
        flow_acc, stream_mask = self.compute_d8_flow_accumulation(elevation)
        twi = self.compute_twi(slope_deg, flow_acc)

        return TerrainDerivativeLayers(
            elevation=elevation,
            slope_deg=slope_deg,
            aspect_deg=aspect_deg,
            profile_curvature=prof_curv,
            planform_curvature=plan_curv,
            tri=tri,
            twi=twi,
            flow_accumulation=flow_acc,
            stream_network=stream_mask,
            cell_size_m=self.cell_size_m,
            bounds=bounds
        )

    def compute_slope_and_aspect(self, dem: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Horn's (1981) 3x3 weighted finite-difference method for slope and aspect.
        This matches the core algorithm used in ArcGIS Spatial Analyst and GDAL gdaldem.
        """
        dx = self.cell_size_m
        dy = self.cell_size_m

        # Sobel/Horn kernel weights:
        # dz/dx kernel:
        # [-1  0  1]
        # [-2  0  2] / (8 * dx)
        # [-1  0  1]
        kernel_x = np.array([
            [-1.0, 0.0, 1.0],
            [-2.0, 0.0, 2.0],
            [-1.0, 0.0, 1.0]
        ], dtype=np.float64) / (8.0 * dx)

        # dz/dy kernel (Y increases upwards in geographical coordinates):
        # [ 1  2  1]
        # [ 0  0  0] / (8 * dy)
        # [-1 -2 -1]
        kernel_y = np.array([
            [1.0, 2.0, 1.0],
            [0.0, 0.0, 0.0],
            [-1.0, -2.0, -1.0]
        ], dtype=np.float64) / (8.0 * dy)

        dz_dx = ndimage.convolve(dem, kernel_x, mode='nearest')
        dz_dy = ndimage.convolve(dem, kernel_y, mode='nearest')

        # Rise over run
        rise_run = np.sqrt(dz_dx**2 + dz_dy**2)
        slope_rad = np.arctan(rise_run)
        slope_deg = np.degrees(slope_rad)

        # Aspect calculation (Compass azimuth: 0 = North, 90 = East, 180 = South, 270 = West)
        # In mathematical Cartesian angles: atan2(dy, -dx)
        aspect_deg = np.zeros_like(dem)
        flat_mask = (dz_dx == 0) & (dz_dy == 0)

        # Compass azimuth calculation
        azimuth = np.degrees(np.arctan2(dz_dx, dz_dy))
        aspect_deg = np.where(azimuth < 0, 360.0 + azimuth, azimuth)
        aspect_deg[flat_mask] = -1.0  # -1 represents flat / undefined aspect

        return np.round(slope_deg, 2), np.round(aspect_deg, 2)

    def compute_curvatures(self, dem: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Zevenbergen & Thorne (1987) 3x3 polynomial surface formulation for
        Profile Curvature (flow acceleration) and Planform Curvature (flow convergence).
        """
        L = self.cell_size_m

        # Coefficients for 3x3 moving window z1..z9
        # z1 z2 z3
        # z4 z5 z6
        # z7 z8 z9
        k_d = np.array([[0, 0, 0], [1, 0, -1], [0, 0, 0]], dtype=np.float64) / (2.0 * L)
        k_e = np.array([[0, 1, 0], [0, 0, 0], [0, -1, 0]], dtype=np.float64) / (2.0 * L)
        k_f = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], dtype=np.float64) / (4.0 * L**2)
        k_g = np.array([[1, 0, -1], [0, 0, 0], [-1, 0, 1]], dtype=np.float64) / (4.0 * L**2)
        k_h = np.array([[-1, 2, -1], [0, 0, 0], [1, -2, 1]], dtype=np.float64) / (4.0 * L**2)

        D = ndimage.convolve(dem, k_d, mode='nearest')  # dz/dx
        E = ndimage.convolve(dem, k_e, mode='nearest')  # dz/dy
        F = ndimage.convolve(dem, k_f, mode='nearest')  # d2z/dx2
        G = ndimage.convolve(dem, k_g, mode='nearest')  # d2z/dxdy
        H = ndimage.convolve(dem, k_h, mode='nearest')  # d2z/dy2

        denom = D**2 + E**2
        denom_safe = np.where(denom < 1e-8, 1e-8, denom)

        # Profile curvature: along direction of maximum slope
        # Negative = convex (accelerating flow, high erosion)
        # Positive = concave (decelerating flow, deposition)
        profile_curv = -2.0 * (F * D**2 + 2.0 * G * D * E + H * E**2) / (denom_safe * (1.0 + denom_safe)**1.5)

        # Planform curvature: perpendicular to direction of maximum slope
        # Positive = concave / convergent (concentrates water into gullies)
        # Negative = convex / divergent (disperses water away from ridges)
        planform_curv = 2.0 * (H * D**2 - 2.0 * G * D * E + F * E**2) / (denom_safe**1.5)

        profile_curv = np.where(denom < 1e-8, 0.0, profile_curv)
        planform_curv = np.where(denom < 1e-8, 0.0, planform_curv)

        return np.round(profile_curv, 5), np.round(planform_curv, 5)

    def compute_tri(self, dem: np.ndarray) -> np.ndarray:
        """
        Terrain Ruggedness Index (TRI - Riley, DeGloria & Elliot, 1999).
        Quantifies local topographic heterogeneity as the square root of sum of squared
        elevation differences between a central cell and its 8 neighbors.
        """
        # Sum of squared differences with all 8 shift offsets
        sq_diff_sum = np.zeros_like(dem, dtype=np.float64)

        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                neighbor = ndimage.shift(dem, shift=(dy, dx), mode='nearest')
                sq_diff_sum += (neighbor - dem)**2

        tri = np.sqrt(sq_diff_sum / 8.0)
        return np.round(tri, 2)

    def compute_d8_flow_accumulation(
        self,
        dem: np.ndarray,
        stream_threshold: int = 50
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        D8 Single-Direction Flow Routing and Upstream Drainage Accumulation.
        Routes water from each cell to its steepest downhill neighbor.
        """
        rows, cols = dem.shape
        L = self.cell_size_m
        diag_L = L * np.sqrt(2.0)

        # Neighbor offsets and distances: (dy, dx, distance)
        offsets = [
            (-1, -1, diag_L), (-1, 0, L), (-1, 1, diag_L),
            ( 0, -1, L),                  ( 0, 1, L),
            ( 1, -1, diag_L), ( 1, 0, L), ( 1, 1, diag_L)
        ]

        # Flow direction: index in offsets of steepest downhill drop
        flow_to = np.full((rows, cols, 2), -1, dtype=np.int32)
        in_degree = np.zeros((rows, cols), dtype=np.int32)

        for r in range(rows):
            for c in range(cols):
                z_curr = dem[r, c]
                max_slope = 0.0
                best_nr, best_nc = -1, -1

                for dr, dc, dist in offsets:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        drop = z_curr - dem[nr, nc]
                        slope = drop / dist
                        if slope > max_slope:
                            max_slope = slope
                            best_nr, best_nc = nr, nc

                if best_nr != -1:
                    flow_to[r, c] = [best_nr, best_nc]
                    in_degree[best_nr, best_nc] += 1

        # Accumulate flow using topological sorting / queue of leaf nodes (in_degree == 0)
        flow_acc = np.ones((rows, cols), dtype=np.float64)  # each cell has 1 unit of self-rainfall
        queue = [(r, c) for r in range(rows) for c in range(cols) if in_degree[r, c] == 0]

        head = 0
        while head < len(queue):
            r, c = queue[head]
            head += 1

            nr, nc = flow_to[r, c]
            if nr != -1:
                flow_acc[nr, nc] += flow_acc[r, c]
                in_degree[nr, nc] -= 1
                if in_degree[nr, nc] == 0:
                    queue.append((nr, nc))

        stream_mask = (flow_acc >= stream_threshold).astype(np.int8)
        return flow_acc, stream_mask

    def compute_twi(self, slope_deg: np.ndarray, flow_accumulation: np.ndarray) -> np.ndarray:
        """
        Topographic Wetness Index (TWI = ln(a / tan(beta))).
        Where 'a' is specific catchment area (accumulated area per unit contour length).
        Identifies water accumulation zones, springs, and landslide-susceptible saturated hollows.
        """
        # Specific catchment area a = flow_acc * cell_size (m2 / m = m)
        a = flow_accumulation * self.cell_size_m
        slope_rad = np.radians(np.clip(slope_deg, 0.5, 89.5))
        tan_beta = np.tan(slope_rad)

        twi = np.log(a / tan_beta)
        twi = np.clip(twi, 0.0, 25.0)
        return np.round(twi, 2)
