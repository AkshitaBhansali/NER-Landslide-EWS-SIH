"""
Infrastructure and Sensor Vector Layer Engine
============================================
Generates georeferenced vector datasets for critical lifelines, transportation,
settlements, hydrological features, and IoT sensor networks across the
Kohima–Dimapur (NH-29 / Dzüdza River) landslide corridor.

Supports standard GeoJSON FeatureCollections and spatial attribute schemas.
"""

from __future__ import annotations
import json
import numpy as np
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, asdict


@dataclass
class InfrastructureDataset:
    roads: Dict[str, Any]
    settlements: Dict[str, Any]
    rivers: Dict[str, Any]
    critical_assets: Dict[str, Any]
    sensors: Dict[str, Any]


class InfrastructureEngine:
    """Generates realistic infrastructure vector geometries and criticality attributes."""

    def __init__(self, bounds: Tuple[float, float, float, float] = (94.02, 25.62, 94.14, 25.72)):
        self.min_lon, self.min_lat, self.max_lon, self.max_lat = bounds

    def generate_all(self, random_seed: int = 42) -> InfrastructureDataset:
        """Generates all 5 vector infrastructure layers formatted as GeoJSON."""
        roads = self.generate_roads()
        settlements = self.generate_settlements()
        rivers = self.generate_rivers()
        critical_assets = self.generate_critical_assets()
        sensors = self.generate_sensor_network(random_seed=random_seed)

        return InfrastructureDataset(
            roads=roads,
            settlements=settlements,
            rivers=rivers,
            critical_assets=critical_assets,
            sensors=sensors
        )

    def generate_roads(self) -> Dict[str, Any]:
        """
        Generates NH-29 (National Highway Lifeline) segmented into 1-km chainage sectors,
        plus regional mountain connector roads and bypasses.
        """
        features = []

        # NH-29 Highway alignment (winding mountain highway running NE across the terrain)
        # Waypoints from Dimapur side (SW) to Kohima town (NE)
        nh29_waypoints = [
            (94.025, 25.625), (94.032, 25.632), (94.041, 25.638),
            (94.048, 25.645), (94.055, 25.652), (94.062, 25.660),
            (94.070, 25.668), (94.078, 25.674), (94.088, 25.680),
            (94.095, 25.688), (94.105, 25.695), (94.118, 25.705),
            (94.128, 25.712), (94.135, 25.718)
        ]

        # Segment NH-29 into numbered monitoring sectors
        for i in range(len(nh29_waypoints) - 1):
            p1 = nh29_waypoints[i]
            p2 = nh29_waypoints[i+1]
            chainage_km = 142 + i
            features.append({
                "type": "Feature",
                "id": f"NH29_SEC_{i+1:02d}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(p1), list(p2)]
                },
                "properties": {
                    "asset_id": f"NH29_SEC_{i+1:02d}",
                    "name": f"NH-29 Sector {i+1} (Km {chainage_km})",
                    "road_type": "National Highway",
                    "criticality_weight": 1.0,  # Critical national lifeline connecting Manipur/Nagaland
                    "traffic_pcu_per_day": 12500,
                    "width_m": 12.0,
                    "pavement_type": "Asphalt / Bituminous",
                    "chainage_start_km": chainage_km,
                    "chainage_end_km": chainage_km + 1
                }
            })

        # Arterial Mountain Link: Zubza - Sechü Village Bypass
        zubza_link = [
            (94.055, 25.652), (94.058, 25.658), (94.064, 25.665),
            (94.069, 25.672), (94.074, 25.679), (94.078, 25.674)
        ]
        features.append({
            "type": "Feature",
            "id": "RD_ZUBZA_LINK",
            "geometry": {
                "type": "LineString",
                "coordinates": zubza_link
            },
            "properties": {
                "asset_id": "RD_ZUBZA_LINK",
                "name": "Zubza-Sechü Hill Arterial",
                "road_type": "State / District Road",
                "criticality_weight": 0.75,
                "traffic_pcu_per_day": 3400,
                "width_m": 7.0,
                "pavement_type": "WBM / Paved"
            }
        })

        # Hill Spur Access: Khonoma Cultural Access Route
        khonoma_link = [
            (94.041, 25.638), (94.038, 25.648), (94.042, 25.659), (94.048, 25.670)
        ]
        features.append({
            "type": "Feature",
            "id": "RD_KHONOMA_SPUR",
            "geometry": {
                "type": "LineString",
                "coordinates": khonoma_link
            },
            "properties": {
                "asset_id": "RD_KHONOMA_SPUR",
                "name": "Khonoma Valley Spur Road",
                "road_type": "Rural Arterial",
                "criticality_weight": 0.60,
                "traffic_pcu_per_day": 1800,
                "width_m": 5.5,
                "pavement_type": "Single Lane Paved"
            }
        })

        return {"type": "FeatureCollection", "name": "transportation_network", "features": features}

    def generate_settlements(self) -> Dict[str, Any]:
        """Generates village and township polygons/points across the mountain slopes."""
        villages = [
            {
                "id": "VIL_ZUBZA",
                "name": "Sechü Zubza",
                "lon": 94.062, "lat": 25.663,
                "population": 3850, "households": 620,
                "criticality_weight": 0.90,
                "has_medical": True, "has_school": True,
                "slope_position": "Mid-slope colluvial terrace"
            },
            {
                "id": "VIL_MEDZIPHEMA_SUB",
                "name": "Old Medziphema Foothills",
                "lon": 94.035, "lat": 25.630,
                "population": 2900, "households": 480,
                "criticality_weight": 0.85,
                "has_medical": True, "has_school": True,
                "slope_position": "Valley alluvial fan"
            },
            {
                "id": "VIL_PHESAMA_NORTH",
                "name": "Phesama North Sector",
                "lon": 94.120, "lat": 25.702,
                "population": 2150, "households": 340,
                "criticality_weight": 0.88,
                "has_medical": False, "has_school": True,
                "slope_position": "Steep debris slope"
            },
            {
                "id": "VIL_TSIESEMA",
                "name": "Tsiesema Hill Settlement",
                "lon": 94.100, "lat": 25.692,
                "population": 1640, "households": 260,
                "criticality_weight": 0.80,
                "has_medical": False, "has_school": True,
                "slope_position": "Ridge spur"
            },
            {
                "id": "VIL_DZUDZA_HAMLET",
                "name": "Dzüdza Riverside Hamlet",
                "lon": 94.072, "lat": 25.655,
                "population": 820, "households": 135,
                "criticality_weight": 0.95,  # High vulnerability to toe erosion and flash floods
                "has_medical": False, "has_school": False,
                "slope_position": "Active toe slope / riverbank"
            }
        ]

        features = []
        for v in villages:
            features.append({
                "type": "Feature",
                "id": v["id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [v["lon"], v["lat"]]
                },
                "properties": {
                    "asset_id": v["id"],
                    "name": v["name"],
                    "asset_type": "Settlement",
                    "population": v["population"],
                    "households": v["households"],
                    "criticality_weight": v["criticality_weight"],
                    "has_medical_facility": v["has_medical"],
                    "has_school": v["has_school"],
                    "geomorphological_position": v["slope_position"]
                }
            })

        return {"type": "FeatureCollection", "name": "human_settlements", "features": features}

    def generate_rivers(self) -> Dict[str, Any]:
        """Generates the primary river channels and flash-flood torrent alignments."""
        features = []

        # Dzüdza River (Major canyon stream that causes severe toe-scour landslides)
        dzudza_coords = [
            [94.032, 25.718], [94.040, 25.705], [94.048, 25.688],
            [94.055, 25.670], [94.062, 25.655], [94.070, 25.642],
            [94.078, 25.632], [94.088, 25.622]
        ]
        features.append({
            "type": "Feature",
            "id": "RIV_DZUDZA",
            "geometry": {
                "type": "LineString",
                "coordinates": dzudza_coords
            },
            "properties": {
                "river_id": "RIV_DZUDZA",
                "name": "Dzüdza River",
                "type": "Perennial Mountain River",
                "mean_discharge_m3_s": 45.0,
                "flash_flood_vulnerability": "High",
                "erosion_potential": "Severe Toe Under-cutting"
            }
        })

        # Chathe River Tributary
        chathe_tributary = [
            [94.022, 25.660], [94.030, 25.650], [94.042, 25.645], [94.055, 25.640]
        ]
        features.append({
            "type": "Feature",
            "id": "RIV_CHATHE_TRIB",
            "geometry": {
                "type": "LineString",
                "coordinates": chathe_tributary
            },
            "properties": {
                "river_id": "RIV_CHATHE_TRIB",
                "name": "Chathe River Tributary",
                "type": "Seasonal Torrent",
                "mean_discharge_m3_s": 18.0,
                "flash_flood_vulnerability": "Moderate",
                "erosion_potential": "Gully Incision"
            }
        })

        return {"type": "FeatureCollection", "name": "drainage_network", "features": features}

    def generate_critical_assets(self) -> Dict[str, Any]:
        """Generates bridges, electrical transmission towers, and emergency facilities."""
        assets = [
            {
                "id": "BRG_DZUDZA_01",
                "name": "Dzüdza Major Bridge (NH-29)",
                "type": "Bridge",
                "lon": 94.062, "lat": 25.660,
                "criticality": 1.0,
                "replacement_cost_cr": 45.0,
                "impact": "Severance of NH-29 stops all freight into Nagaland & Manipur"
            },
            {
                "id": "BRG_ZUBZA_CULVERT",
                "name": "Zubza Double-Cell RC Culvert",
                "type": "Culvert",
                "lon": 94.088, "lat": 25.680,
                "criticality": 0.85,
                "replacement_cost_cr": 8.5,
                "impact": "Local debris blockage threatens 120 upstream households"
            },
            {
                "id": "TWR_PWR_132KV_44",
                "name": "132kV Transmission Tower #44",
                "type": "Electric Transmission Tower",
                "lon": 94.075, "lat": 25.670,
                "criticality": 0.92,
                "replacement_cost_cr": 6.2,
                "impact": "Grid failure would black out Kohima & Tuensang districts"
            },
            {
                "id": "TWR_PWR_132KV_45",
                "name": "132kV Transmission Tower #45",
                "type": "Electric Transmission Tower",
                "lon": 94.082, "lat": 25.677,
                "criticality": 0.90,
                "replacement_cost_cr": 5.8,
                "impact": "High-voltage line collapse onto highway below"
            },
            {
                "id": "MED_ZUBZA_CHC",
                "name": "Sechü Zubza Community Health Center",
                "type": "Healthcare Facility",
                "lon": 94.064, "lat": 25.664,
                "criticality": 0.95,
                "replacement_cost_cr": 18.0,
                "impact": "Primary emergency medical triage point for the corridor"
            },
            {
                "id": "TEL_TOWER_AIRTEL_09",
                "name": "Emergency Telecom BTS Hub",
                "type": "Telecommunications",
                "lon": 94.095, "lat": 25.689,
                "criticality": 0.88,
                "replacement_cost_cr": 3.5,
                "impact": "Loss of emergency alert broadcasting and GSM connectivity"
            }
        ]

        features = []
        for a in assets:
            features.append({
                "type": "Feature",
                "id": a["id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [a["lon"], a["lat"]]
                },
                "properties": {
                    "asset_id": a["id"],
                    "name": a["name"],
                    "asset_type": a["type"],
                    "criticality_weight": a["criticality"],
                    "replacement_cost_inr_cr": a["replacement_cost_cr"],
                    "failure_impact_description": a["impact"]
                }
            })

        return {"type": "FeatureCollection", "name": "critical_infrastructure", "features": features}

    def generate_sensor_network(self, random_seed: int = 42) -> Dict[str, Any]:
        """
        Generates IoT Early Warning Sensor array matching Saksham/Eisa's SENSOR_READING_SCHEMA:
        Piezometers, Inclinometers, Rain Gauges, and Soil Moisture sensors.
        """
        rng = np.random.default_rng(random_seed)

        sensor_configs = [
            ("SNS_PIEZO_01", "Pore Pressure Piezometer PZ-01", "Piezometer", "kPa", 94.058, 25.655, "ZONE_NH29_ZUBZA"),
            ("SNS_PIEZO_02", "Pore Pressure Piezometer PZ-02", "Piezometer", "kPa", 94.072, 25.671, "ZONE_NH29_ZUBZA"),
            ("SNS_INCLINO_01", "Borehole Inclinometer IN-01", "Inclinometer", "mm/day", 94.062, 25.661, "ZONE_DZUDZA_BRIDGE"),
            ("SNS_INCLINO_02", "Surface Tiltmeter TL-02", "Tiltmeter", "arcsec", 94.076, 25.673, "ZONE_TOWER44_SLOPE"),
            ("SNS_RAIN_01", "Tipping Bucket Rain Gauge RG-01", "Rain Gauge", "mm/hr", 94.065, 25.666, "ZONE_ZUBZA_CHC"),
            ("SNS_RAIN_02", "Automatic Weather Station AWS-02", "Rain Gauge", "mm/hr", 94.110, 25.698, "ZONE_KOHIMA_WEST"),
            ("SNS_SOIL_01", "FDR Soil Moisture Probe SM-01", "Soil Moisture", "% Vol", 94.060, 25.658, "ZONE_NH29_ZUBZA"),
            ("SNS_SOIL_02", "TDR Soil Moisture Probe SM-02", "Soil Moisture", "% Vol", 94.085, 25.679, "ZONE_TSIESEMA_SPUR"),
            ("SNS_SEISMIC_01", "Micro-seismic Acoustic Sensor MS-01", "Acoustic Emission", "dB", 94.070, 25.669, "ZONE_DZUDZA_GORGE"),
            ("SNS_GNSS_01", "Differential GNSS Station GNSS-01", "GNSS Displacement", "mm", 94.063, 25.659, "ZONE_DZUDZA_BRIDGE")
        ]

        features = []
        for sid, name, stype, unit, lon, lat, zone in sensor_configs:
            # Simulate sensor health scores matching SensorHealthScorer
            health_score = int(rng.integers(75, 100))
            battery_pct = int(rng.integers(68, 99))
            rssi_dbm = int(rng.integers(-88, -55))
            status = "Healthy" if health_score >= 80 else ("Degraded" if health_score >= 60 else "Failed")

            features.append({
                "type": "Feature",
                "id": sid,
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "properties": {
                    "sensor_id": sid,
                    "name": name,
                    "sensor_type": stype,
                    "unit": unit,
                    "zone_id": zone,
                    "health_score": health_score,
                    "battery_pct": battery_pct,
                    "rssi_dbm": rssi_dbm,
                    "status": status,
                    "sampling_interval_s": 60,
                    "telemetry_protocol": "LoRaWAN / 4G-Fallback"
                }
            })

        return {"type": "FeatureCollection", "name": "iot_sensor_network", "features": features}
