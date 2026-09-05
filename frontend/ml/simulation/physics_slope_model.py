"""
Physics-Informed Synthetic Scenario Generator
=============================================

Purpose
-------
Generates a synthetic scenario dataset labelled by slope-stability physics
rather than by an arbitrary rule, so that the ML layer learns a physically
grounded relationship and reports contributing factors that map back to real
geotechnical quantities.

Model
-----
The infinite slope stability model with rainfall-driven transient pore-water
pressure, which is the standard formulation for shallow rainfall-triggered
soil and colluvium slides, and the class of model used by regional early
warning systems and the geotechnical literature (for example Iverson, 2000,
"Landslide triggering by rain infiltration"). Rockfall trajectory models do
not apply here, because a landslide is a mass failure along a slip surface
rather than a discrete falling body.

Factor of Safety for an infinite slope with pore pressure at depth z:

    FS = [ c + (gamma*z*cos^2(beta) - u) * tan(phi) ]
         ----------------------------------------------
                 gamma * z * sin(beta) * cos(beta)

  c      effective soil cohesion (kPa)
  phi    effective friction angle (deg)
  gamma  soil unit weight (kN/m3)
  z      depth to the potential slip surface (m)
  beta   slope angle (deg)
  u      pore-water pressure at depth z (kPa), driven by rainfall infiltration

Pore pressure is modelled through a saturation ratio m, where 0 is dry and 1
is a fully saturated slip surface, built from an antecedent-precipitation
rainfall memory relative to soil infiltration and storage capacity. This is
the same quantity carried by the antecedent_precip_index field in the
historical schema, so both layers use a consistent definition:

    u = m * gamma_w * z * cos^2(beta)      (gamma_w = 9.81 kN/m3)

Risk bands
----------
    FS < 1.0          mechanically unstable, failure predicted
    1.0 <= FS < 1.3   marginal, high risk
    1.3 <= FS < 1.8   moderate
    FS >= 1.8         stable
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass

GAMMA_WATER = 9.81  # kN/m3


@dataclass
class SlopeScenarioParams:
    n: int = 40000
    slope_deg_min: float = 10.0
    slope_deg_max: float = 70.0
    depth_m_min: float = 0.5     # shallow soil slides: typically 0.5-3m to slip surface
    depth_m_max: float = 4.0
    cohesion_kpa_mean: float = 8.0     # residual/colluvial soils: low cohesion
    cohesion_kpa_std: float = 4.0
    friction_angle_deg_mean: float = 30.0
    friction_angle_deg_std: float = 5.0
    unit_weight_kn_m3_mean: float = 18.0
    unit_weight_kn_m3_std: float = 2.0
    porosity_mean: float = 0.42
    porosity_std: float = 0.08


class LandslidePhysicsSimulator:
    """Generates a synthetic scenario dataset labeled by infinite-slope Factor of Safety."""

    def __init__(self, random_state: int = 42, params: SlopeScenarioParams | None = None):
        self.rng = np.random.default_rng(random_state)
        self.p = params or SlopeScenarioParams()

    def _sample_geotech(self, n):
        cohesion = np.clip(self.rng.normal(self.p.cohesion_kpa_mean, self.p.cohesion_kpa_std, n), 0.5, 40)
        phi = np.clip(self.rng.normal(self.p.friction_angle_deg_mean, self.p.friction_angle_deg_std, n), 15, 42)
        gamma = np.clip(self.rng.normal(self.p.unit_weight_kn_m3_mean, self.p.unit_weight_kn_m3_std, n), 14, 22)
        porosity = np.clip(self.rng.normal(self.p.porosity_mean, self.p.porosity_std, n), 0.25, 0.6)
        return cohesion, phi, gamma, porosity

    def _sample_rainfall(self, n):
        """Rainfall regime sampled to span dry season through NER monsoon extremes
        (Meghalaya-scale cloudburst events included in the tail)."""
        rainfall_24h = self.rng.gamma(shape=1.4, scale=25, size=n)          # heavy right tail
        rainfall_72h = rainfall_24h * self.rng.uniform(1.6, 3.0, n)
        rainfall_7d = rainfall_72h * self.rng.uniform(1.3, 2.4, n)
        return rainfall_24h, rainfall_72h, rainfall_7d

    def generate(self) -> pd.DataFrame:
        n = self.p.n
        slope_deg = self.rng.uniform(self.p.slope_deg_min, self.p.slope_deg_max, n)
        depth_m = self.rng.uniform(self.p.depth_m_min, self.p.depth_m_max, n)
        cohesion, phi, gamma, porosity = self._sample_geotech(n)
        rainfall_24h, rainfall_72h, rainfall_7d = self._sample_rainfall(n)

        # antecedent precipitation index - exponentially weighted rainfall memory,
        # same construction the historical schema uses (feature parity across
        # real and synthetic data, required for the two datasets to be combinable)
        api = 0.5 * rainfall_7d + 0.35 * rainfall_72h + 0.15 * rainfall_24h

        # Saturation ratio m: how much of the failure-plane depth is effectively
        # saturated, as a function of antecedent rainfall relative to the soil's
        # own storage capacity (porosity * depth). Capped at 1 (fully saturated).
        storage_capacity_mm = porosity * depth_m * 1000  # m -> mm of equivalent water
        m = np.clip(api / (storage_capacity_mm + 1e-6), 0.0, 1.0)

        beta = np.radians(slope_deg)
        u = m * GAMMA_WATER * depth_m * np.cos(beta) ** 2

        numerator = cohesion + (gamma * depth_m * np.cos(beta) ** 2 - u) * np.tan(np.radians(phi))
        denominator = gamma * depth_m * np.sin(beta) * np.cos(beta)
        fs = numerator / np.clip(denominator, 1e-6, None)
        fs = np.clip(fs, 0.05, 8.0)  # numerically bound; FS>8 is "obviously stable," not informative

        # Contributing-factor decomposition: how much each term contributes to
        # instability, expressed as a share of the resisting-force deficit -
        # this is what feeds `contributing_factors` in the ML output, not a
        # post-hoc feature-importance guess.
        cohesion_share = cohesion / np.clip(numerator, 1e-6, None)
        friction_share = ((gamma * depth_m * np.cos(beta) ** 2 - u) * np.tan(np.radians(phi))) / np.clip(numerator, 1e-6, None)
        pore_pressure_penalty = (u * np.tan(np.radians(phi))) / np.clip(numerator + u * np.tan(np.radians(phi)), 1e-6, None)

        # Label: stochastic threshold near FS=1 rather than a hard cutoff, since
        # real slope failure has natural scatter around the theoretical FS=1
        # boundary, reflecting spatial heterogeneity that a point model cannot
        # capture.
        failure_prob_physics = 1 / (1 + np.exp((fs - 1.0) * 4.0))  # logistic centered at FS=1
        landslide_occurred = (self.rng.random(n) < failure_prob_physics).astype(int)

        df = pd.DataFrame({
            "slope_deg": slope_deg,
            "depth_to_slip_surface_m": depth_m,
            "cohesion_kpa": cohesion,
            "friction_angle_deg": phi,
            "unit_weight_kn_m3": gamma,
            "porosity": porosity,
            "rainfall_24h_mm": rainfall_24h,
            "rainfall_72h_mm": rainfall_72h,
            "rainfall_7d_mm": rainfall_7d,
            "antecedent_precip_index": api,
            "saturation_ratio": m,
            "pore_pressure_kpa": u,
            "factor_of_safety": fs,
            "cohesion_contribution": cohesion_share,
            "friction_contribution": friction_share,
            "pore_pressure_contribution": pore_pressure_penalty,
            "failure_probability_physics": failure_prob_physics,
            "landslide_occurred": landslide_occurred,
        })
        return df


def risk_level_from_fs(fs: float) -> str:
    if fs < 1.0:
        return "Critical"
    elif fs < 1.3:
        return "High"
    elif fs < 1.8:
        return "Moderate"
    return "Low"


if __name__ == "__main__":
    sim = LandslidePhysicsSimulator(random_state=42)
    df = sim.generate()
    df["risk_level"] = df["factor_of_safety"].apply(risk_level_from_fs)

    out_path = "../data/synthetic_slope_scenarios.csv"
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} physics-informed scenarios -> {out_path}")
    print(f"\nEvent rate: {df['landslide_occurred'].mean():.2%}")
    print(f"\nRisk level distribution:\n{df['risk_level'].value_counts()}")
    print(f"\nFS summary:\n{df['factor_of_safety'].describe()}")
