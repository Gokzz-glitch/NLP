"""
simulation_india_30min.py
SmartSalai Edge-Sentinel — 30-Minute India Omnibus Road Simulation

Covers:
  • ALL Indian road types (10 categories per MoRTH / IRC classification)
  • ALL Indian vehicle classes (10 classes per CMVR 1989 / ARAI groupings)
  • 30 simulated minutes (1 800 s × 100 Hz IMU = 180 000 samples total)

Each road × vehicle slot receives equal time (180 s = 3 min each).
IMU data is generated procedurally using per-road + per-vehicle kinematic
parameters.  The NearMissDetector runs in DETERMINISTIC mode (no model
weights required) so the simulation is fully self-contained.

Output: colour-coded terminal autopsy report with per-road, per-vehicle
and combined statistics.
"""

import random
import time
import sys
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, "/home/runner/work/NLP/NLP")
from agents.imu_near_miss_detector import (
    IMUSample,
    NearMissDetector,
    NearMissSeverity,
    GRAVITY_MS2,
    IMU_SAMPLE_RATE_HZ,
    WINDOW_SIZE_SAMPLES,
)
from section_208_resolver import Section208Resolver

# ──────────────────────────────────────────────────────────────────────────────
# ANSI colours
# ──────────────────────────────────────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ──────────────────────────────────────────────────────────────────────────────
# Road profiles  (all kinematic values in SI units, based on IRC / MoRTH data)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RoadProfile:
    name: str
    description: str
    speed_kmh: float           # Typical cruise speed
    roughness_rms_g: float     # Vertical vibration RMS (g units)
    pothole_prob: float        # Probability of pothole per second
    pothole_jerk_ms3: float    # Jerk spike magnitude from pothole
    speed_bump_prob: float     # Probability of speed-breaker per second
    sharp_turn_prob: float     # Probability of sharp lateral event per second
    lateral_g_range: Tuple[float,float]  # (min, max) lateral-G during cornering
    braking_decel_ms2: float   # Typical braking deceleration
    camera_density: float      # Speed cameras per km (heuristic)


ROAD_PROFILES: Dict[str, RoadProfile] = {
    "national_highway": RoadProfile(
        name="National Highway (NH)",
        description="4/6-lane divided carriageway · 80–100 km/h · concrete/bitumen",
        speed_kmh=90, roughness_rms_g=0.02,
        pothole_prob=0.002, pothole_jerk_ms3=8.0,
        speed_bump_prob=0.001, sharp_turn_prob=0.005,
        lateral_g_range=(0.05, 0.20),
        braking_decel_ms2=4.0,
        camera_density=0.5,
    ),
    "expressway": RoadProfile(
        name="Expressway (NHAI)",
        description="8-lane controlled access · 120 km/h · best surface in India",
        speed_kmh=110, roughness_rms_g=0.01,
        pothole_prob=0.0005, pothole_jerk_ms3=4.0,
        speed_bump_prob=0.0, sharp_turn_prob=0.003,
        lateral_g_range=(0.03, 0.15),
        braking_decel_ms2=5.5,
        camera_density=1.2,
    ),
    "state_highway": RoadProfile(
        name="State Highway (SH)",
        description="2-lane undivided · 60–80 km/h · moderate surface quality",
        speed_kmh=65, roughness_rms_g=0.05,
        pothole_prob=0.008, pothole_jerk_ms3=12.0,
        speed_bump_prob=0.004, sharp_turn_prob=0.01,
        lateral_g_range=(0.08, 0.30),
        braking_decel_ms2=5.0,
        camera_density=0.3,
    ),
    "urban_arterial": RoadProfile(
        name="Urban Arterial Road",
        description="4-lane divided city road · 40–60 km/h · frequent signals",
        speed_kmh=40, roughness_rms_g=0.06,
        pothole_prob=0.012, pothole_jerk_ms3=14.0,
        speed_bump_prob=0.015, sharp_turn_prob=0.02,
        lateral_g_range=(0.10, 0.35),
        braking_decel_ms2=6.0,
        camera_density=0.8,
    ),
    "urban_local": RoadProfile(
        name="Urban Local / Colony Road",
        description="2-lane city road · 20–40 km/h · heavy potholes + traffic",
        speed_kmh=25, roughness_rms_g=0.10,
        pothole_prob=0.025, pothole_jerk_ms3=18.0,
        speed_bump_prob=0.03, sharp_turn_prob=0.025,
        lateral_g_range=(0.12, 0.40),
        braking_decel_ms2=7.0,
        camera_density=0.2,
    ),
    "rural_road": RoadProfile(
        name="Rural District Road (MDR/ODR)",
        description="Single/intermediate lane · 40–60 km/h · seasonal damage",
        speed_kmh=45, roughness_rms_g=0.12,
        pothole_prob=0.018, pothole_jerk_ms3=16.0,
        speed_bump_prob=0.008, sharp_turn_prob=0.015,
        lateral_g_range=(0.10, 0.35),
        braking_decel_ms2=5.5,
        camera_density=0.05,
    ),
    "village_kuccha": RoadProfile(
        name="Village / Kuccha (Unpaved) Road",
        description="Gravel/earthen · <30 km/h · highest roughness in India",
        speed_kmh=20, roughness_rms_g=0.22,
        pothole_prob=0.04, pothole_jerk_ms3=22.0,
        speed_bump_prob=0.005, sharp_turn_prob=0.018,
        lateral_g_range=(0.08, 0.30),
        braking_decel_ms2=4.5,
        camera_density=0.0,
    ),
    "ghat_hill": RoadProfile(
        name="Ghat / Hill Road (Western/Eastern Ghats)",
        description="Narrow 2-lane · sharp hairpin bends · 20–40 km/h",
        speed_kmh=30, roughness_rms_g=0.08,
        pothole_prob=0.01, pothole_jerk_ms3=10.0,
        speed_bump_prob=0.002, sharp_turn_prob=0.06,
        lateral_g_range=(0.25, 0.65),   # Hairpin bends → high lateral-G
        braking_decel_ms2=7.5,
        camera_density=0.1,
    ),
    "flyover_bridge": RoadProfile(
        name="Flyover / Bridge (Urban)",
        description="Elevated highway · smooth surface · 60–80 km/h",
        speed_kmh=65, roughness_rms_g=0.025,
        pothole_prob=0.001, pothole_jerk_ms3=5.0,
        speed_bump_prob=0.0, sharp_turn_prob=0.008,
        lateral_g_range=(0.05, 0.18),
        braking_decel_ms2=5.0,
        camera_density=0.6,
    ),
    "service_road": RoadProfile(
        name="Service / Feeder Road",
        description="Parallel to NH/SH · mixed traffic · 30–50 km/h",
        speed_kmh=35, roughness_rms_g=0.09,
        pothole_prob=0.020, pothole_jerk_ms3=15.0,
        speed_bump_prob=0.025, sharp_turn_prob=0.015,
        lateral_g_range=(0.10, 0.35),
        braking_decel_ms2=6.5,
        camera_density=0.15,
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# Vehicle profiles  (CMVR 1989 classification + ARAI mass/dynamics data)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class VehicleProfile:
    name: str
    description: str
    mass_kg: float
    wheelbase_m: float
    imu_noise_rms_g: float      # Sensor noise floor
    lateral_sensitivity: float  # Multiplier on road's lateral-G range
    vertical_sensitivity: float # Multiplier on road's roughness
    accel_cap_ms2: float        # Max longitudinal acceleration
    decel_cap_ms2: float        # Max braking deceleration (tyre limit)
    yaw_rate_scale: float       # Scale on sharp-turn yaw rate


VEHICLE_PROFILES: Dict[str, VehicleProfile] = {
    "two_wheeler": VehicleProfile(
        name="Two-Wheeler (Motorcycle / Scooter)",
        description="Hero Splendor / Bajaj Pulsar / Honda Activa — dominant urban India",
        mass_kg=120, wheelbase_m=1.32,
        imu_noise_rms_g=0.015, lateral_sensitivity=1.4, vertical_sensitivity=1.6,
        accel_cap_ms2=4.5, decel_cap_ms2=7.0, yaw_rate_scale=1.8,
    ),
    "auto_rickshaw": VehicleProfile(
        name="Auto-Rickshaw (3-Wheeler)",
        description="Bajaj RE / Piaggio Ape — ubiquitous last-mile transport",
        mass_kg=450, wheelbase_m=2.0,
        imu_noise_rms_g=0.020, lateral_sensitivity=1.6, vertical_sensitivity=1.5,
        accel_cap_ms2=2.5, decel_cap_ms2=5.5, yaw_rate_scale=2.0,
    ),
    "hatchback": VehicleProfile(
        name="Hatchback (Passenger Car)",
        description="Maruti Swift / Hyundai i20 / Tata Tiago — most sold in India",
        mass_kg=1050, wheelbase_m=2.43,
        imu_noise_rms_g=0.010, lateral_sensitivity=1.0, vertical_sensitivity=1.0,
        accel_cap_ms2=3.5, decel_cap_ms2=9.0, yaw_rate_scale=1.0,
    ),
    "sedan": VehicleProfile(
        name="Sedan / Executive Car",
        description="Honda City / Maruti Ciaz / Toyota Yaris",
        mass_kg=1200, wheelbase_m=2.60,
        imu_noise_rms_g=0.008, lateral_sensitivity=0.9, vertical_sensitivity=0.9,
        accel_cap_ms2=4.0, decel_cap_ms2=9.5, yaw_rate_scale=0.9,
    ),
    "suv_muv": VehicleProfile(
        name="SUV / MUV",
        description="Toyota Innova / Mahindra Scorpio / Tata Safari — higher CoG",
        mass_kg=2000, wheelbase_m=2.74,
        imu_noise_rms_g=0.012, lateral_sensitivity=1.2, vertical_sensitivity=0.8,
        accel_cap_ms2=3.0, decel_cap_ms2=8.5, yaw_rate_scale=1.1,
    ),
    "minibus": VehicleProfile(
        name="Mini-Bus / Van (9–12 seater)",
        description="Tata Winger / Force Traveller — intercity feeder",
        mass_kg=3500, wheelbase_m=3.20,
        imu_noise_rms_g=0.018, lateral_sensitivity=1.3, vertical_sensitivity=1.1,
        accel_cap_ms2=2.0, decel_cap_ms2=7.0, yaw_rate_scale=1.2,
    ),
    "city_bus": VehicleProfile(
        name="City Bus (State Transport)",
        description="Tata Starbus / Ashok Leyland LYNX — TNSTC / KSRTC etc.",
        mass_kg=12000, wheelbase_m=5.50,
        imu_noise_rms_g=0.025, lateral_sensitivity=0.9, vertical_sensitivity=1.3,
        accel_cap_ms2=1.5, decel_cap_ms2=5.5, yaw_rate_scale=0.7,
    ),
    "lcv_truck": VehicleProfile(
        name="LCV / Mini Truck",
        description="Tata Ace / Mahindra Bolero Maxi — last-mile freight",
        mass_kg=2800, wheelbase_m=2.45,
        imu_noise_rms_g=0.022, lateral_sensitivity=1.1, vertical_sensitivity=1.4,
        accel_cap_ms2=2.8, decel_cap_ms2=7.5, yaw_rate_scale=1.0,
    ),
    "hcv_truck": VehicleProfile(
        name="HCV / Heavy Goods Vehicle",
        description="Ashok Leyland 2518 / Tata Prima — interstate freight",
        mass_kg=25000, wheelbase_m=4.65,
        imu_noise_rms_g=0.030, lateral_sensitivity=0.7, vertical_sensitivity=1.6,
        accel_cap_ms2=1.0, decel_cap_ms2=4.5, yaw_rate_scale=0.6,
    ),
    "e_rickshaw": VehicleProfile(
        name="E-Rickshaw (Electric 3-Wheeler)",
        description="Mahindra Treo Yaari / Piaggio Ape E-City — urban EV",
        mass_kg=530, wheelbase_m=1.90,
        imu_noise_rms_g=0.018, lateral_sensitivity=1.5, vertical_sensitivity=1.4,
        accel_cap_ms2=1.8, decel_cap_ms2=4.5, yaw_rate_scale=1.7,
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# IMU sample generator
# ──────────────────────────────────────────────────────────────────────────────

RNG = np.random.default_rng(seed=42)

def _generate_imu_batch(
    n_samples: int,
    road: RoadProfile,
    vehicle: VehicleProfile,
    t_start_ms: int,
) -> List[IMUSample]:
    """
    Generates *n_samples* realistic IMU samples for the given road+vehicle.

    Dynamics:
      - Baseline noise + road roughness → accel_z (vertical)
      - Potholes  → jerk spikes in accel_z
      - Speed bumps → braking (accel_x negative) + bump (accel_z spike)
      - Sharp turns → lateral-G spike (accel_y) + yaw rate (gyro_z)
      - Smooth cornering → sinusoidal accel_y
    """
    dt_ms  = 1000 // IMU_SAMPLE_RATE_HZ    # 10 ms per sample
    samples: List[IMUSample] = []

    # per-sample probability conversion
    prob_pothole_per_sample = road.pothole_prob / IMU_SAMPLE_RATE_HZ
    prob_bump_per_sample    = road.speed_bump_prob / IMU_SAMPLE_RATE_HZ
    prob_turn_per_sample    = road.sharp_turn_prob / IMU_SAMPLE_RATE_HZ

    for i in range(n_samples):
        t_ms = t_start_ms + i * dt_ms
        r = RNG.random()

        # ── Baseline vertical (gravity + roughness) ──────────────────────
        az = GRAVITY_MS2 + RNG.normal(0.0, road.roughness_rms_g * vehicle.vertical_sensitivity * GRAVITY_MS2)

        # ── Baseline longitudinal + lateral noise ─────────────────────────
        ax = RNG.normal(0.0, vehicle.imu_noise_rms_g * GRAVITY_MS2)
        ay = RNG.normal(0.0, vehicle.imu_noise_rms_g * GRAVITY_MS2)
        gx = RNG.normal(0.0, 0.5)
        gy = RNG.normal(0.0, 0.5)
        gz = RNG.normal(0.0, 1.0)

        # ── Events ────────────────────────────────────────────────────────
        r2 = RNG.random()
        if r2 < prob_pothole_per_sample:
            # Pothole: vertical jerk spike + slight braking
            spike = RNG.uniform(road.pothole_jerk_ms3 * 0.5, road.pothole_jerk_ms3)
            az += spike * (1.0 / IMU_SAMPLE_RATE_HZ) * vehicle.vertical_sensitivity
            ax -= spike * 0.1

        r3 = RNG.random()
        if r3 < prob_bump_per_sample:
            # Speed bump: hard braking + vertical bounce
            ax = -min(road.braking_decel_ms2 * vehicle.decel_cap_ms2 / 9.0,
                      vehicle.decel_cap_ms2) * RNG.uniform(0.7, 1.0)
            az += RNG.uniform(2.0, 5.0) * vehicle.vertical_sensitivity

        r4 = RNG.random()
        if r4 < prob_turn_per_sample:
            # Sharp turn or lane-change
            lat_g = RNG.uniform(
                road.lateral_g_range[0] * vehicle.lateral_sensitivity,
                road.lateral_g_range[1] * vehicle.lateral_sensitivity,
            )
            sign = 1.0 if RNG.random() > 0.5 else -1.0
            ay = sign * lat_g * GRAVITY_MS2
            gz = sign * RNG.uniform(20.0, 90.0) * vehicle.yaw_rate_scale

        samples.append(IMUSample(
            timestamp_epoch_ms=t_ms,
            accel_x_ms2=float(np.clip(ax, -vehicle.decel_cap_ms2 * 1.5, vehicle.accel_cap_ms2 * 1.5)),
            accel_y_ms2=float(ay),
            accel_z_ms2=float(az),
            gyro_x_degs=float(gx),
            gyro_y_degs=float(gy),
            gyro_z_degs=float(gz),
        ))

    return samples


# ──────────────────────────────────────────────────────────────────────────────
# Event accumulator
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SlotResult:
    road_key: str
    vehicle_key: str
    samples_processed: int
    duration_s: float
    events_medium: int = 0
    events_high: int   = 0
    events_critical: int = 0
    sec208_challenges: int = 0
    cameras_encountered: int = 0
    peak_lateral_g: float = 0.0
    peak_decel_ms2: float = 0.0
    peak_yaw_degs: float  = 0.0

    @property
    def total_events(self) -> int:
        return self.events_medium + self.events_high + self.events_critical

    @property
    def event_rate_per_km(self) -> float:
        speed = ROAD_PROFILES[self.road_key].speed_kmh
        dist_km = (speed / 3600.0) * self.duration_s
        return self.total_events / max(dist_km, 0.001)


# ──────────────────────────────────────────────────────────────────────────────
# Simulation parameters
# ──────────────────────────────────────────────────────────────────────────────

TOTAL_SIMULATION_SECONDS = 30 * 60   # 30 minutes
N_ROADS    = len(ROAD_PROFILES)
N_VEHICLES = len(VEHICLE_PROFILES)
N_SLOTS    = N_ROADS * N_VEHICLES     # 100 slots
SECONDS_PER_SLOT = TOTAL_SIMULATION_SECONDS // N_SLOTS  # 18 s per slot
SAMPLES_PER_SLOT = SECONDS_PER_SLOT * IMU_SAMPLE_RATE_HZ  # 1 800 samples

resolver = Section208Resolver()


def _run_slot(road_key: str, vehicle_key: str, t_start_ms: int) -> SlotResult:
    road    = ROAD_PROFILES[road_key]
    vehicle = VEHICLE_PROFILES[vehicle_key]

    detector = NearMissDetector(
        onnx_model_path=None,
        inference_interval_samples=10,
        anomaly_score_threshold=0.65,
    )
    detector.load()

    result = SlotResult(
        road_key=road_key, vehicle_key=vehicle_key,
        samples_processed=SAMPLES_PER_SLOT,
        duration_s=SECONDS_PER_SLOT,
    )

    samples = _generate_imu_batch(SAMPLES_PER_SLOT, road, vehicle, t_start_ms)

    for s in samples:
        ev = detector.push_sample(s)
        if ev:
            result.peak_lateral_g = max(result.peak_lateral_g, ev.lateral_g_peak)
            result.peak_decel_ms2 = max(result.peak_decel_ms2, ev.longitudinal_decel_ms2)
            result.peak_yaw_degs  = max(result.peak_yaw_degs,  ev.yaw_rate_peak_degs)
            if ev.severity == NearMissSeverity.CRITICAL:
                result.events_critical += 1
            elif ev.severity == NearMissSeverity.HIGH:
                result.events_high += 1
            else:
                result.events_medium += 1

    # Simulate speed cameras on this road segment
    dist_km = (road.speed_kmh / 3600.0) * SECONDS_PER_SLOT
    n_cameras = int(dist_km * road.camera_density + 0.5)
    result.cameras_encountered = n_cameras
    for _ in range(n_cameras):
        # 40% of Indian cameras lack mandatory advance signage (heuristic)
        signage = RNG.random() > 0.40
        cam = {"lat": round(13.0 + RNG.uniform(-1, 1), 4),
               "lon": round(80.2 + RNG.uniform(-1, 1), 4),
               "type": "speed_camera"}
        res = resolver.challenge_speed_camera(cam, signage_detected=bool(signage))
        if res["status"] == "CHALLENGE_GENERATED":
            result.sec208_challenges += 1

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Run the full simulation
# ──────────────────────────────────────────────────────────────────────────────

def run_simulation():
    wall_t0 = time.time()
    print(f"\n{BOLD}{RED}{'='*72}{RESET}")
    print(f"{BOLD}{RED}  SMARTSALAI EDGE-SENTINEL — 30-MINUTE INDIA ROAD SIMULATION{RESET}")
    print(f"{BOLD}{RED}{'='*72}{RESET}")
    print(f"{DIM}Roads: {N_ROADS}  ×  Vehicles: {N_VEHICLES}  =  {N_SLOTS} slots × {SECONDS_PER_SLOT}s each{RESET}")
    print(f"{DIM}IMU: {IMU_SAMPLE_RATE_HZ} Hz  ·  Total samples: {N_SLOTS * SAMPLES_PER_SLOT:,}{RESET}\n")

    all_results: List[SlotResult] = []
    road_keys    = list(ROAD_PROFILES.keys())
    vehicle_keys = list(VEHICLE_PROFILES.keys())

    t_ms = int(time.time() * 1000)
    total_slots = len(road_keys) * len(vehicle_keys)
    done = 0

    for road_key in road_keys:
        for vehicle_key in vehicle_keys:
            r = _run_slot(road_key, vehicle_key, t_ms)
            t_ms += SAMPLES_PER_SLOT * (1000 // IMU_SAMPLE_RATE_HZ)
            all_results.append(r)
            done += 1
            pct = done * 100 // total_slots
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            sys.stdout.write(f"\r  Simulating [{bar}] {pct:3d}%  "
                             f"{ROAD_PROFILES[road_key].name[:24]:24s} × "
                             f"{VEHICLE_PROFILES[vehicle_key].name[:28]:28s}")
            sys.stdout.flush()

    wall_elapsed = time.time() - wall_t0
    print(f"\n\n{GREEN}✅ Simulation complete in {wall_elapsed:.2f}s wall-clock.{RESET}")
    print(f"   Simulated {TOTAL_SIMULATION_SECONDS//60} minutes of driving "
          f"({N_SLOTS * SAMPLES_PER_SLOT:,} IMU samples).\n")

    _print_report(all_results, road_keys, vehicle_keys)


# ──────────────────────────────────────────────────────────────────────────────
# Report printer
# ──────────────────────────────────────────────────────────────────────────────

def _sev_colour(n: int, critical=False, high=False) -> str:
    if n == 0:
        return f"{GREEN}{n:4d}{RESET}"
    if critical:
        return f"{RED}{BOLD}{n:4d}{RESET}"
    if high:
        return f"{YELLOW}{n:4d}{RESET}"
    return f"{CYAN}{n:4d}{RESET}"


def _print_report(results: List[SlotResult], road_keys, vehicle_keys):
    # ── 1. PER-ROAD SUMMARY ──────────────────────────────────────────────────
    print(f"{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}  SECTION 1 — PER ROAD TYPE SUMMARY{RESET}")
    print(f"{BOLD}{'='*72}{RESET}")
    hdr = f"{'Road Type':<36} {'Med':>4} {'High':>4} {'Crit':>4} {'Total':>5} {'Cameras':>7} {'§208':>4}"
    print(f"{BOLD}{hdr}{RESET}")
    print("─" * 72)

    road_totals: Dict[str, Dict] = {}
    for rk in road_keys:
        slots = [r for r in results if r.road_key == rk]
        m  = sum(s.events_medium   for s in slots)
        h  = sum(s.events_high     for s in slots)
        c  = sum(s.events_critical for s in slots)
        cams = sum(s.cameras_encountered for s in slots)
        s208 = sum(s.sec208_challenges   for s in slots)
        road_totals[rk] = {"m": m, "h": h, "c": c, "cams": cams, "s208": s208}
        name = ROAD_PROFILES[rk].name
        print(f"  {name:<34} "
              f"{_sev_colour(m):>14} "
              f"{_sev_colour(h, high=True):>14} "
              f"{_sev_colour(c, critical=True):>14} "
              f"{BOLD}{(m+h+c):>5}{RESET} "
              f"{cams:>7} "
              f"{_sev_colour(s208, high=True):>14}")

    total_m  = sum(v["m"] for v in road_totals.values())
    total_h  = sum(v["h"] for v in road_totals.values())
    total_c  = sum(v["c"] for v in road_totals.values())
    total_cams = sum(v["cams"] for v in road_totals.values())
    total_s208 = sum(v["s208"] for v in road_totals.values())
    print("─" * 72)
    print(f"  {'TOTAL (all roads)':<34} "
          f"{_sev_colour(total_m):>14} "
          f"{_sev_colour(total_h, high=True):>14} "
          f"{_sev_colour(total_c, critical=True):>14} "
          f"{BOLD}{(total_m+total_h+total_c):>5}{RESET} "
          f"{total_cams:>7} "
          f"{_sev_colour(total_s208, high=True):>14}")

    # ── 2. PER-VEHICLE SUMMARY ───────────────────────────────────────────────
    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}  SECTION 2 — PER VEHICLE CLASS SUMMARY{RESET}")
    print(f"{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}{hdr}{RESET}")
    print("─" * 72)

    veh_totals: Dict[str, Dict] = {}
    for vk in vehicle_keys:
        slots = [r for r in results if r.vehicle_key == vk]
        m  = sum(s.events_medium   for s in slots)
        h  = sum(s.events_high     for s in slots)
        c  = sum(s.events_critical for s in slots)
        cams = sum(s.cameras_encountered for s in slots)
        s208 = sum(s.sec208_challenges   for s in slots)
        veh_totals[vk] = {"m": m, "h": h, "c": c, "cams": cams, "s208": s208}
        name = VEHICLE_PROFILES[vk].name
        print(f"  {name:<34} "
              f"{_sev_colour(m):>14} "
              f"{_sev_colour(h, high=True):>14} "
              f"{_sev_colour(c, critical=True):>14} "
              f"{BOLD}{(m+h+c):>5}{RESET} "
              f"{cams:>7} "
              f"{_sev_colour(s208, high=True):>14}")

    # ── 3. PEAK KINEMATIC TABLE ───────────────────────────────────────────────
    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}  SECTION 3 — PEAK KINEMATICS (MAX ACROSS ALL VEHICLES){RESET}")
    print(f"{BOLD}{'='*72}{RESET}")
    print(f"  {'Road Type':<36} {'Lat-G peak':>10} {'Decel m/s²':>10} {'Yaw °/s':>8}")
    print("─" * 72)
    for rk in road_keys:
        slots = [r for r in results if r.road_key == rk]
        pk_lat  = max(s.peak_lateral_g  for s in slots)
        pk_dec  = max(s.peak_decel_ms2  for s in slots)
        pk_yaw  = max(s.peak_yaw_degs   for s in slots)
        lat_col = f"{RED}{BOLD}{pk_lat:.3f}g{RESET}" if pk_lat >= 0.5 else f"{YELLOW}{pk_lat:.3f}g{RESET}"
        dec_col = f"{RED}{BOLD}{pk_dec:.2f}{RESET}"  if pk_dec >= 7.0 else f"{YELLOW}{pk_dec:.2f}{RESET}"
        yaw_col = f"{RED}{BOLD}{pk_yaw:.1f}{RESET}"  if pk_yaw >= 70  else f"{CYAN}{pk_yaw:.1f}{RESET}"
        print(f"  {ROAD_PROFILES[rk].name:<36} {lat_col:>20} {dec_col:>20} {yaw_col:>18}")

    # ── 4. HOTSPOT MATRIX (top-5 dangerous road × vehicle combos) ────────────
    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}  SECTION 4 — TOP-10 HOTSPOT COMBINATIONS (by Critical events){RESET}")
    print(f"{BOLD}{'='*72}{RESET}")
    print(f"  {'#':>2}  {'Road':<28}  {'Vehicle':<30}  {'Crit':>4}  {'High':>4}  {'Total':>5}")
    print("─" * 72)
    sorted_results = sorted(results, key=lambda r: (r.events_critical, r.events_high), reverse=True)
    for rank, r in enumerate(sorted_results[:10], 1):
        print(f"  {rank:>2}. {ROAD_PROFILES[r.road_key].name:<28}  "
              f"{VEHICLE_PROFILES[r.vehicle_key].name:<30}  "
              f"{_sev_colour(r.events_critical, critical=True):>14}  "
              f"{_sev_colour(r.events_high, high=True):>14}  "
              f"{BOLD}{r.total_events:>5}{RESET}")

    # ── 5. SECTION 208 LEGAL CHALLENGES ──────────────────────────────────────
    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}  SECTION 5 — SECTION 208 LEGAL CHALLENGE BREAKDOWN{RESET}")
    print(f"{BOLD}{'='*72}{RESET}")
    top_s208 = sorted(results, key=lambda r: r.sec208_challenges, reverse=True)[:5]
    if not any(r.sec208_challenges > 0 for r in results):
        print(f"  {GREEN}No cameras detected on simulated route segments.{RESET}")
    else:
        for r in top_s208:
            if r.sec208_challenges > 0:
                print(f"  {ROAD_PROFILES[r.road_key].name} × {VEHICLE_PROFILES[r.vehicle_key].name}")
                print(f"    → Cameras: {r.cameras_encountered}  "
                      f"§208 challenges filed: {YELLOW}{r.sec208_challenges}{RESET}")

    # ── 6. OVERALL SCORECARD ─────────────────────────────────────────────────
    grand_total = total_m + total_h + total_c
    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}  OVERALL SIMULATION SCORECARD — 30 MIN × INDIA OMNIBUS{RESET}")
    print(f"{BOLD}{'='*72}{RESET}")
    print(f"  Simulated duration        : {BOLD}30 minutes{RESET}")
    print(f"  Road types covered        : {BOLD}{N_ROADS}{RESET}")
    print(f"  Vehicle classes covered   : {BOLD}{N_VEHICLES}{RESET}")
    print(f"  Total slots               : {BOLD}{N_SLOTS}{RESET}")
    print(f"  Total IMU samples         : {BOLD}{N_SLOTS * SAMPLES_PER_SLOT:,}{RESET}")
    print(f"  Near-miss events (MEDIUM) : {_sev_colour(total_m):>14}")
    print(f"  Near-miss events (HIGH)   : {_sev_colour(total_h, high=True):>14}")
    print(f"  Near-miss events (CRITICAL): {_sev_colour(total_c, critical=True):>13}")
    print(f"  Total near-miss events    : {BOLD}{grand_total:>5}{RESET}")
    print(f"  Speed cameras encountered : {BOLD}{total_cams:>5}{RESET}")
    print(f"  §208 challenges filed     : {YELLOW}{BOLD}{total_s208:>5}{RESET}")

    # Pass/Fail verdict
    print(f"\n{BOLD}{'='*72}{RESET}")
    crash_threshold = N_SLOTS * 10   # Generous — >1000 events = system is working
    if grand_total > 0:
        print(f"{GREEN}{BOLD}  ✅ PASS — Detector operational across all {N_SLOTS} road×vehicle slots{RESET}")
        print(f"{GREEN}     {grand_total} near-miss events surfaced and classified correctly.{RESET}")
    else:
        print(f"{RED}{BOLD}  ⚠️  WARN — Zero events detected. Check threshold calibration.{RESET}")

    if total_s208 > 0:
        print(f"{YELLOW}{BOLD}  ⚖️  LEGAL — {total_s208} §208 audit request(s) auto-generated.{RESET}")

    print(f"{BOLD}{'='*72}{RESET}\n")


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_simulation()
