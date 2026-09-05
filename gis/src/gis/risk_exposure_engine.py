"""
Spatial Risk Mapping and Infrastructure Exposure Prioritization Engine
=====================================================================
Ingests continuous terrain derivatives and time-series rainfall/ML risk scenarios,
projects continuous 2D/3D risk heatmaps, and performs spatial intersection
exposure analysis against critical infrastructure networks.

Formula for Infrastructure Prioritization:
    Priority Score = Hazard Risk Score * Asset Criticality Weight * Vulnerability Factor
"""

from __future__ import annotations
import numpy as np
import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Tuple, Optional
from src.gis.dem_engine import DEMGrid
from src.gis.terrain_derivatives import TerrainDerivativeLayers


@dataclass
class TimeStepRiskGrid:
    time_label: str             # "T+0h", "T+6h", "T+12h", "T+24h", "T+48h", "T+72h"
    rainfall_24h_mm: float
    rainfall_72h_mm: float
    rainfall_7d_mm: float
    mean_risk_score: float
    max_risk_score: float
    high_risk_area_km2: float
    risk_grid: np.ndarray       # 2D array of risk scores (0.0 to 100.0)
    risk_levels: np.ndarray     # 2D array of risk categories (0: Low, 1: Moderate, 2: High, 3: Severe)


@dataclass
class ExposedAssetReport:
    asset_id: str
    asset_name: str
    asset_type: str
    criticality_weight: float
    max_hazard_risk: float
    priority_score: float
    status: str
    threat_description: str
    recommended_action: str


@dataclass
class CorridorExposureReport:
    time_label: str
    monsoon_scenario: str
    total_exposed_road_km: float
    threatened_population: int
    critical_assets_at_risk_count: int
    ranked_priority_list: List[ExposedAssetReport]
    evacuation_alert_level: str


class RiskExposureEngine:
    """Computes continuous spatial landslide risk grids and evaluates infrastructure vulnerability."""

    def __init__(self, dem: DEMGrid, derivatives: TerrainDerivativeLayers):
        self.dem = dem
        self.derivatives = derivatives
        self.cell_area_km2 = (dem.cell_size_m * dem.cell_size_m) / 1_000_000.0

    def compute_infinite_slope_risk_grid(
        self,
        rainfall_24h_mm: float,
        rainfall_72h_mm: float,
        rainfall_7d_mm: float,
        antecedent_precip_index: float,
        time_label: str = "T+24h"
    ) -> TimeStepRiskGrid:
        """
        Evaluates physical slope stability and ML observable risk features
        across every cell of the DEM grid.
        
        Uses infinite slope Factor of Safety physics:
        FS = [c + (gamma * z * cos^2(beta) - u) * tan(phi)] / [gamma * z * sin(beta) * cos(beta)]
        where u = pore pressure driven by rainfall infiltration modulated by TWI (Topographic Wetness Index).
        """
        slope_deg = self.derivatives.slope_deg
        twi = self.derivatives.twi

        # Geotechnical priors for Nagaland Disang Shales / Colluvium
        c = 10.0          # cohesion (kPa)
        phi_deg = 28.0    # internal friction angle
        phi_rad = np.radians(phi_deg)
        gamma = 18.5      # unit weight of soil (kN/m3)
        gamma_w = 9.81    # unit weight of water (kN/m3)
        z = 2.0           # average slip surface depth (m)

        beta_rad = np.radians(np.clip(slope_deg, 1.0, 85.0))
        cos_beta = np.cos(beta_rad)
        sin_beta = np.sin(beta_rad)

        # Infiltration saturation ratio (m) driven by cumulative rain + TWI convergence
        # TWI concentrates water into slope hollows and drainage pathways
        twi_normalized = np.clip((twi - 3.0) / 10.0, 0.0, 1.5)
        base_sat = (antecedent_precip_index / 120.0) + (rainfall_72h_mm / 250.0)
        m = np.clip(base_sat * (1.0 + 0.4 * twi_normalized), 0.0, 1.0)

        # Pore-water pressure (kPa)
        u = m * gamma_w * z * (cos_beta**2)

        # Driving stress (shear)
        tau = gamma * z * sin_beta * cos_beta
        tau = np.where(tau < 0.1, 0.1, tau)

        # Resisting stress (shear strength)
        sigma_eff = (gamma * z * (cos_beta**2)) - u
        sigma_eff = np.clip(sigma_eff, 0.0, None)
        s = c + sigma_eff * np.tan(phi_rad)

        # Factor of Safety (FoS)
        fos = s / tau

        # Map FoS to continuous Risk Score (0 - 100)
        # FoS > 2.0 -> Risk ~ 5-15 (Low)
        # FoS 1.3-1.8 -> Risk ~ 30-55 (Moderate)
        # FoS 1.0-1.3 -> Risk ~ 60-80 (High)
        # FoS < 1.0 -> Risk ~ 85-100 (Severe / Failure Imminent)
        risk_score = 100.0 / (1.0 + np.exp(2.8 * (fos - 1.25)))
        risk_score = np.round(np.clip(risk_score, 0.0, 100.0), 2)

        # Categorical risk level
        risk_levels = np.zeros_like(risk_score, dtype=np.int8)
        risk_levels[risk_score >= 35.0] = 1   # Moderate
        risk_levels[risk_score >= 60.0] = 2   # High
        risk_levels[risk_score >= 80.0] = 3   # Severe

        high_risk_cells = np.sum(risk_score >= 60.0)
        high_risk_area = high_risk_cells * self.cell_area_km2

        return TimeStepRiskGrid(
            time_label=time_label,
            rainfall_24h_mm=rainfall_24h_mm,
            rainfall_72h_mm=rainfall_72h_mm,
            rainfall_7d_mm=rainfall_7d_mm,
            mean_risk_score=float(np.mean(risk_score)),
            max_risk_score=float(np.max(risk_score)),
            high_risk_area_km2=float(round(high_risk_area, 3)),
            risk_grid=risk_score,
            risk_levels=risk_levels
        )

    def simulate_advancing_monsoon_scenario(self) -> List[TimeStepRiskGrid]:
        """
        Simulates 6 sequential operational timesteps representing an advancing
        extreme Bay of Bengal monsoon depression over Kohima.
        """
        scenarios = [
            ("T+0h (Dry Antecedent)", 10.0, 25.0, 45.0, 20.0),
            ("T+6h (Onset of Infiltration)", 35.0, 55.0, 75.0, 42.0),
            ("T+12h (Continuous Heavy Rain)", 75.0, 110.0, 130.0, 78.0),
            ("T+24h (Monsoon Peak Torrent)", 140.0, 210.0, 240.0, 135.0),
            ("T+48h (Soil Saturated State)", 185.0, 290.0, 340.0, 190.0),
            ("T+72h (Post-Peak Saturation)", 95.0, 330.0, 420.0, 220.0),
        ]

        results = []
        for label, r24, r72, r7d, api in scenarios:
            grid = self.compute_infinite_slope_risk_grid(
                rainfall_24h_mm=r24,
                rainfall_72h_mm=r72,
                rainfall_7d_mm=r7d,
                antecedent_precip_index=api,
                time_label=label
            )
            results.append(grid)

        return results

    def evaluate_exposure_and_prioritization(
        self,
        risk_grid: TimeStepRiskGrid,
        infrastructure: Any
    ) -> CorridorExposureReport:
        """
        Performs spatial overlay intersection between the continuous risk grid
        and vector infrastructure layers to compute R x I prioritized action list.
        """
        ranked_assets: List[ExposedAssetReport] = []
        total_exposed_road_km = 0.0
        threatened_pop = 0
        critical_assets_threatened = 0

        grid = risk_grid.risk_grid

        # 1. Evaluate Transportation (NH-29 sectors and hill roads)
        for f in infrastructure.roads["features"]:
            props = f["properties"]
            coords = f["geometry"]["coordinates"]

            # Sample risk along road coordinates
            segment_risks = []
            for pt in coords:
                lon, lat = pt[0], pt[1]
                r, c = self.dem.coord_to_indices(lon, lat)
                segment_risks.append(grid[r, c])

            max_risk = float(np.max(segment_risks))
            crit = float(props.get("criticality_weight", 0.7))
            p_score = round(max_risk * crit, 2)

            if max_risk >= 50.0:
                length_km = float(props.get("chainage_end_km", 1) - props.get("chainage_start_km", 0)) if "chainage_start_km" in props else 1.2
                total_exposed_road_km += length_km

                status = "Critical Closure Threat" if max_risk >= 75.0 else "High Warning / Slope Deformation"
                threat = f"Severe debris flow & cut-slope failure expected along {props['name']}."
                action = "Deploy NDRF clearance machines, close traffic, and divert via bypass." if max_risk >= 75.0 else "Deploy traffic spotters and enforce single-lane movement."

                ranked_assets.append(ExposedAssetReport(
                    asset_id=props["asset_id"],
                    asset_name=props["name"],
                    asset_type="Highway / Transportation",
                    criticality_weight=crit,
                    max_hazard_risk=max_risk,
                    priority_score=p_score,
                    status=status,
                    threat_description=threat,
                    recommended_action=action
                ))

        # 2. Evaluate Settlements
        for f in infrastructure.settlements["features"]:
            props = f["properties"]
            lon, lat = f["geometry"]["coordinates"]
            r, c = self.dem.coord_to_indices(lon, lat)

            # Check 3x3 surrounding terrain window to catch upslope failures
            rmin, rmax = max(0, r-2), min(self.dem.rows, r+3)
            cmin, cmax = max(0, c-2), min(self.dem.cols, c+3)
            surrounding_risk = float(np.max(grid[rmin:rmax, cmin:cmax]))

            crit = float(props.get("criticality_weight", 0.85))
            p_score = round(surrounding_risk * crit, 2)

            if surrounding_risk >= 55.0:
                threatened_pop += props["population"]
                status = "Immediate Evacuation Alert" if surrounding_risk >= 75.0 else "Pre-Evacuation Warning"
                threat = f"Colluvial debris slide threatens {props['population']} residents in {props['name']}."
                action = f"Initiate Level-3 evacuation to community relief shelters." if surrounding_risk >= 75.0 else f"Alert village headman (Gaon Bura) and prepare community halls."

                ranked_assets.append(ExposedAssetReport(
                    asset_id=props["asset_id"],
                    asset_name=props["name"],
                    asset_type="Settlement",
                    criticality_weight=crit,
                    max_hazard_risk=surrounding_risk,
                    priority_score=p_score,
                    status=status,
                    threat_description=threat,
                    recommended_action=action
                ))

        # 3. Evaluate Critical Assets (Bridges, Power Towers, Medical)
        for f in infrastructure.critical_assets["features"]:
            props = f["properties"]
            lon, lat = f["geometry"]["coordinates"]
            r, c = self.dem.coord_to_indices(lon, lat)

            rmin, rmax = max(0, r-1), min(self.dem.rows, r+2)
            cmin, cmax = max(0, c-1), min(self.dem.cols, c+2)
            surrounding_risk = float(np.max(grid[rmin:rmax, cmin:cmax]))

            crit = float(props.get("criticality_weight", 0.9))
            p_score = round(surrounding_risk * crit, 2)

            if surrounding_risk >= 50.0:
                critical_assets_threatened += 1
                status = "Structural Threat / Scour Alert" if surrounding_risk >= 75.0 else "Asset Monitored"
                threat = f"{props['name']} ({props['asset_type']}) exposed to foundation scouring and toe collapse."
                action = "Isolate electrical grid / inspect bridge abutments immediately." if surrounding_risk >= 75.0 else "Inspect structural inclinometers every 30 minutes."

                ranked_assets.append(ExposedAssetReport(
                    asset_id=props["asset_id"],
                    asset_name=props["name"],
                    asset_type=props["asset_type"],
                    criticality_weight=crit,
                    max_hazard_risk=surrounding_risk,
                    priority_score=p_score,
                    status=status,
                    threat_description=threat,
                    recommended_action=action
                ))

        # Sort all exposed assets strictly by Prioritization Score (R x I)
        ranked_assets.sort(key=lambda a: a.priority_score, reverse=True)

        alert_level = "RED (Severe Emergency)" if risk_grid.max_risk_score >= 80.0 else ("ORANGE (High Alert)" if risk_grid.max_risk_score >= 60.0 else "YELLOW (Advisory)")

        return CorridorExposureReport(
            time_label=risk_grid.time_label,
            monsoon_scenario=f"24h Rain: {risk_grid.rainfall_24h_mm}mm | 7d Rain: {risk_grid.rainfall_7d_mm}mm",
            total_exposed_road_km=round(total_exposed_road_km, 1),
            threatened_population=threatened_pop,
            critical_assets_at_risk_count=critical_assets_threatened,
            ranked_priority_list=ranked_assets,
            evacuation_alert_level=alert_level
        )
