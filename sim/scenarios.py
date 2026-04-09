"""
sim/scenarios.py
SmartSalai Edge-Sentinel — Indian Road Condition Scenario Configurations

Each scenario approximates a distinct real-world Indian road context using:
  - Kinematic parameters (speed, jerk, lateral-G) derived from IRC/MoRTH data
  - Environmental factors (visibility, glare, rain) as metadata
  - Camera density (speed cameras per km) from TN TASMAC enforcement data

Used by sim/run_video_sim.py and tests/simulation_india_30min.py to generate
synthetic sensor streams for offline evaluation.

IMPORTANT: All values are simulation parameters for research only.
           Do NOT use these as real-world safety thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class RoadScenario:
    """Configuration for a single Indian road driving scenario."""
    name: str
    description: str

    # Kinematic parameters
    speed_kmh: float               # Typical cruise speed (km/h)
    roughness_rms_g: float         # Vertical vibration RMS (g-units, IRC-8)
    pothole_prob_per_s: float      # Probability of pothole event per simulated second
    pothole_jerk_ms3: float        # Jerk spike magnitude from pothole (m/s³)
    speed_bump_prob_per_s: float   # Probability of speed-breaker per simulated second
    sharp_turn_prob_per_s: float   # Probability of lateral event per simulated second
    lateral_g_range: Tuple[float, float]  # (min, max) lateral-G during cornering
    braking_decel_ms2: float       # Typical braking deceleration (m/s²)
    camera_density_per_km: float   # Speed cameras per km (heuristic, TN data)

    # Environmental factors (metadata, not kinematic)
    visibility: str = "clear"      # "clear" | "night" | "rain" | "fog" | "glare"
    traffic_density: str = "medium" # "low" | "medium" | "high" | "gridlock"
    road_user_mix: str = "mixed"   # "bikes" | "mixed" | "trucks" | "pedestrian"


# ──────────────────────────────────────────────────────────────────────────────
# Baseline road-type scenarios (IRC road classification)
# ──────────────────────────────────────────────────────────────────────────────

ROAD_SCENARIOS: Dict[str, RoadScenario] = {
    "national_highway_day": RoadScenario(
        name="National Highway — Day",
        description="4/6-lane divided carriageway; 80–100 km/h; bitumen; clear visibility",
        speed_kmh=90.0, roughness_rms_g=0.02,
        pothole_prob_per_s=0.002, pothole_jerk_ms3=8.0,
        speed_bump_prob_per_s=0.001, sharp_turn_prob_per_s=0.005,
        lateral_g_range=(0.05, 0.20), braking_decel_ms2=4.0,
        camera_density_per_km=0.5, visibility="clear", traffic_density="medium",
    ),
    "national_highway_night": RoadScenario(
        name="National Highway — Night",
        description="Same as NH day but reduced visibility; glare from oncoming vehicles",
        speed_kmh=75.0, roughness_rms_g=0.025,
        pothole_prob_per_s=0.004, pothole_jerk_ms3=9.0,
        speed_bump_prob_per_s=0.001, sharp_turn_prob_per_s=0.007,
        lateral_g_range=(0.05, 0.25), braking_decel_ms2=5.0,
        camera_density_per_km=0.5, visibility="night", traffic_density="low",
    ),
    "national_highway_rain": RoadScenario(
        name="National Highway — Heavy Rain",
        description="Monsoon conditions; aquaplaning risk; reduced coefficient of friction",
        speed_kmh=55.0, roughness_rms_g=0.03,
        pothole_prob_per_s=0.005, pothole_jerk_ms3=7.0,
        speed_bump_prob_per_s=0.001, sharp_turn_prob_per_s=0.010,
        lateral_g_range=(0.08, 0.35), braking_decel_ms2=6.5,
        camera_density_per_km=0.5, visibility="rain", traffic_density="low",
    ),
    "state_highway_day": RoadScenario(
        name="State Highway — Day",
        description="2-lane undivided SH; 60–80 km/h; pedestrians and animals present",
        speed_kmh=65.0, roughness_rms_g=0.04,
        pothole_prob_per_s=0.005, pothole_jerk_ms3=10.0,
        speed_bump_prob_per_s=0.003, sharp_turn_prob_per_s=0.010,
        lateral_g_range=(0.08, 0.35), braking_decel_ms2=5.5,
        camera_density_per_km=0.3, visibility="clear", traffic_density="medium",
    ),
    "urban_arterial_day": RoadScenario(
        name="Urban Arterial — Chennai Peak Hour",
        description="6-lane urban road; 30–50 km/h; heavy mixed traffic",
        speed_kmh=35.0, roughness_rms_g=0.06,
        pothole_prob_per_s=0.010, pothole_jerk_ms3=12.0,
        speed_bump_prob_per_s=0.005, sharp_turn_prob_per_s=0.020,
        lateral_g_range=(0.10, 0.45), braking_decel_ms2=7.0,
        camera_density_per_km=1.2, visibility="clear", traffic_density="gridlock",
        road_user_mix="mixed",
    ),
    "urban_arterial_night_glare": RoadScenario(
        name="Urban Arterial — Night + Glare",
        description="Urban road at night; opposing headlight glare; wet patches",
        speed_kmh=40.0, roughness_rms_g=0.07,
        pothole_prob_per_s=0.012, pothole_jerk_ms3=13.0,
        speed_bump_prob_per_s=0.006, sharp_turn_prob_per_s=0.025,
        lateral_g_range=(0.12, 0.50), braking_decel_ms2=7.5,
        camera_density_per_km=1.0, visibility="glare", traffic_density="medium",
    ),
    "rural_single_lane": RoadScenario(
        name="Rural Single-Lane Road",
        description="Narrow rural road; <30 km/h; large potholes; animals",
        speed_kmh=28.0, roughness_rms_g=0.10,
        pothole_prob_per_s=0.020, pothole_jerk_ms3=15.0,
        speed_bump_prob_per_s=0.002, sharp_turn_prob_per_s=0.030,
        lateral_g_range=(0.15, 0.60), braking_decel_ms2=6.0,
        camera_density_per_km=0.05, visibility="clear", traffic_density="low",
        road_user_mix="bikes",
    ),
    "mountain_ghat_day": RoadScenario(
        name="Ghat Road — Nilgiris / Kodaikanal",
        description="Steep hairpin bends; 15–25 km/h; mist; guard-rail sections",
        speed_kmh=20.0, roughness_rms_g=0.05,
        pothole_prob_per_s=0.005, pothole_jerk_ms3=8.0,
        speed_bump_prob_per_s=0.001, sharp_turn_prob_per_s=0.060,
        lateral_g_range=(0.25, 0.70), braking_decel_ms2=8.0,
        camera_density_per_km=0.1, visibility="fog", traffic_density="low",
    ),
    "construction_zone": RoadScenario(
        name="Active Construction Zone",
        description="Road widening / NHAI project; temporary lane changes; debris",
        speed_kmh=20.0, roughness_rms_g=0.15,
        pothole_prob_per_s=0.030, pothole_jerk_ms3=18.0,
        speed_bump_prob_per_s=0.010, sharp_turn_prob_per_s=0.040,
        lateral_g_range=(0.20, 0.65), braking_decel_ms2=9.0,
        camera_density_per_km=0.2, visibility="clear", traffic_density="high",
    ),
    "school_zone_peak": RoadScenario(
        name="School Zone — Dismissal Time",
        description="Dense pedestrian flow; unpredictable child crossings; 25 km/h",
        speed_kmh=22.0, roughness_rms_g=0.05,
        pothole_prob_per_s=0.008, pothole_jerk_ms3=10.0,
        speed_bump_prob_per_s=0.015, sharp_turn_prob_per_s=0.020,
        lateral_g_range=(0.08, 0.40), braking_decel_ms2=8.5,
        camera_density_per_km=0.8, visibility="clear", traffic_density="high",
        road_user_mix="pedestrian",
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# Vehicle class configurations (CMVR 1989 / ARAI groupings)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VehicleClass:
    """Vehicle-specific kinematic modifier."""
    name: str
    mass_kg: float                 # Unladen mass (kg)
    wheelbase_m: float             # (m)
    speed_cap_kmh: float           # Maximum legal speed cap (km/h) in TN
    jerk_multiplier: float         # Relative to baseline (1.0)
    lateral_g_multiplier: float    # Tip-over risk modifier


VEHICLE_CLASSES: Dict[str, VehicleClass] = {
    "two_wheeler_100cc": VehicleClass(
        "Two-Wheeler (<125cc)", mass_kg=110, wheelbase_m=1.25,
        speed_cap_kmh=80, jerk_multiplier=1.4, lateral_g_multiplier=1.6,
    ),
    "two_wheeler_350cc": VehicleClass(
        "Two-Wheeler (125–350cc)", mass_kg=185, wheelbase_m=1.35,
        speed_cap_kmh=100, jerk_multiplier=1.3, lateral_g_multiplier=1.4,
    ),
    "auto_rickshaw": VehicleClass(
        "Auto Rickshaw (3W)", mass_kg=400, wheelbase_m=2.0,
        speed_cap_kmh=60, jerk_multiplier=1.2, lateral_g_multiplier=1.3,
    ),
    "car_compact": VehicleClass(
        "Compact Car (M1)", mass_kg=1000, wheelbase_m=2.5,
        speed_cap_kmh=120, jerk_multiplier=1.0, lateral_g_multiplier=1.0,
    ),
    "car_suv": VehicleClass(
        "SUV / MUV (M1/M2)", mass_kg=1800, wheelbase_m=2.7,
        speed_cap_kmh=120, jerk_multiplier=0.9, lateral_g_multiplier=0.9,
    ),
    "taxi_cab": VehicleClass(
        "Taxi / Cab (M1)", mass_kg=1100, wheelbase_m=2.55,
        speed_cap_kmh=120, jerk_multiplier=1.0, lateral_g_multiplier=1.0,
    ),
    "school_van": VehicleClass(
        "School Van (M2, ≤13 seats)", mass_kg=2200, wheelbase_m=3.1,
        speed_cap_kmh=80, jerk_multiplier=0.85, lateral_g_multiplier=0.85,
    ),
    "ambulance": VehicleClass(
        # SIMULATION RESEARCH ONLY — see SAFETY.md for prohibited real-vehicle uses
        "Ambulance (N1 converted)", mass_kg=3000, wheelbase_m=3.3,
        speed_cap_kmh=100, jerk_multiplier=0.80, lateral_g_multiplier=0.80,
    ),
    "light_truck": VehicleClass(
        "Light Commercial Vehicle (N1)", mass_kg=2500, wheelbase_m=2.9,
        speed_cap_kmh=80, jerk_multiplier=0.95, lateral_g_multiplier=0.90,
    ),
    "heavy_truck": VehicleClass(
        "Heavy Goods Vehicle (N3)", mass_kg=16000, wheelbase_m=5.2,
        speed_cap_kmh=80, jerk_multiplier=0.70, lateral_g_multiplier=0.70,
    ),
}


def all_scenario_vehicle_combinations() -> List[Tuple[str, str]]:
    """Return cross-product of all scenario × vehicle combinations."""
    return [
        (road_key, veh_key)
        for road_key in ROAD_SCENARIOS
        for veh_key in VEHICLE_CLASSES
    ]
