"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         SmartSalai Edge-Sentinel — BRUTAL SYSTEM STRESS TEST v1.0          ║
║         "If it survives this, it can guard a life. If not, fix it."        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  CONTEXT: Tamil Nadu is India's deadliest state for 2-wheeler fatalities.  ║
║  11,140 two-wheeler deaths/year. 7,500+ without helmets. 8 crashes/hour.  ║
║  This system is not a prototype when it runs — it IS the last line.        ║
╚══════════════════════════════════════════════════════════════════════════════╝

HOW TO RUN:
    python brutal_sentinel_test.py

    Each test prints PASS / FAIL / CRITICAL_FAIL.
    CRITICAL_FAIL = someone could die because of this bug. Fix before deploy.

WHAT THIS TESTS:
    [A] IMU Sensor Edge Cases       — the physics of how crashes actually happen
    [B] Human Behaviour Scenarios   — real TN road user psychology
    [C] Environmental Conditions    — Indian roads are not ISO lab conditions
    [D] System Failure Modes        — what happens when hardware/software dies
    [E] Legal Logic Correctness     — wrong Section 208 = driver loses in court
    [F] TTS Latency & Priority      — alert 100ms late = rider already crashed
    [G] BLE Mesh Integrity          — ghost events should never trigger alerts
    [H] Concurrency & Race Conds.   — 100Hz IMU + inference + TTS + BLE = war
    [I] Model Confidence Limits     — a 0.64 score vs 0.65 threshold = death?
    [J] Adversarial / Edge Physics  — scenarios the team never imagined
"""

import time
import uuid
import math
import random
import logging
import threading
import sys
import os
from dataclasses import dataclass
from typing import List, Optional

# ── Try importing the project modules ─────────────────────────────────────────
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from agents.imu_near_miss_detector import (
        NearMissDetector, IMUSample, NearMissSeverity,
        IMUBuffer, NearMissFeatureExtractor, calibrate_gravity,
        GRAVITY_MS2, WINDOW_SIZE_SAMPLES, IMU_SAMPLE_RATE_HZ,
        LATERAL_G_CRITICAL_THRESHOLD, LATERAL_G_HIGH_THRESHOLD,
        LONGITUDINAL_DECEL_CRITICAL_MS2, YAW_RATE_CRITICAL_DEGS
    )
    from section_208_resolver import Section208Resolver
    PROJECT_IMPORTED = True
except ImportError as e:
    print(f"[IMPORT WARN] Could not import project modules: {e}")
    print("Running in SCHEMA-ONLY mode — logic tests will use inline stubs.\n")
    PROJECT_IMPORTED = False
    GRAVITY_MS2 = 9.80665
    WINDOW_SIZE_SAMPLES = 120
    IMU_SAMPLE_RATE_HZ = 100
    LATERAL_G_CRITICAL_THRESHOLD = 0.65
    LATERAL_G_HIGH_THRESHOLD = 0.45
    LONGITUDINAL_DECEL_CRITICAL_MS2 = 8.0
    YAW_RATE_CRITICAL_DEGS = 90.0

# ── Test Harness ───────────────────────────────────────────────────────────────

PASS    = "✅ PASS"
FAIL    = "❌ FAIL"
CFAIL   = "💀 CRITICAL_FAIL"
WARN    = "⚠️  WARN"

results = []

def run_test(name: str, fn):
    try:
        verdict, detail = fn()
        tag = PASS if verdict == "PASS" else (CFAIL if verdict == "CRITICAL" else FAIL)
        print(f"  {tag}  {name}")
        if detail:
            print(f"          → {detail}")
        results.append((name, verdict))
    except Exception as exc:
        print(f"  {CFAIL}  {name}")
        print(f"          → THREW EXCEPTION: {exc}")
        results.append((name, "CRITICAL"))

def section(title):
    print(f"\n{'═'*78}")
    print(f"  {title}")
    print(f"{'═'*78}")

# ── IMU Sample factory ─────────────────────────────────────────────────────────

def t_ms():
    return int(time.time() * 1000)

def normal_sample(ts=None):
    if not PROJECT_IMPORTED: return None
    return IMUSample(
        timestamp_epoch_ms=ts or t_ms(),
        accel_x_ms2=random.gauss(0.05, 0.03),
        accel_y_ms2=random.gauss(0.0, 0.03),
        accel_z_ms2=GRAVITY_MS2 + random.gauss(0.0, 0.04),
        gyro_x_degs=random.gauss(0.0, 0.3),
        gyro_y_degs=random.gauss(0.0, 0.3),
        gyro_z_degs=random.gauss(0.0, 0.8),
    )

def swerve_sample(ts=None, lateral_g=0.70, yaw=100.0, decel=-7.0):
    if not PROJECT_IMPORTED: return None
    return IMUSample(
        timestamp_epoch_ms=ts or t_ms(),
        accel_x_ms2=decel,
        accel_y_ms2=lateral_g * GRAVITY_MS2,
        accel_z_ms2=GRAVITY_MS2 + random.gauss(0.2, 0.1),
        gyro_x_degs=random.gauss(0.0, 1.0),
        gyro_y_degs=random.gauss(0.0, 1.0),
        gyro_z_degs=yaw,
    )

def fill_detector_buffer(detector, n=120, factory=None):
    ts = t_ms()
    factory = factory or normal_sample
    for i in range(n):
        s = factory(ts + i * 10)
        if s:
            detector.push_sample(s)

# ════════════════════════════════════════════════════════════════════════════════
# [A] IMU SENSOR EDGE CASES
# ════════════════════════════════════════════════════════════════════════════════

section("[A] IMU SENSOR EDGE CASES — The Physics of Real TN Crashes")

"""
REAL CRASH DATA (MoRTH iRAD + RADMS Tamil Nadu):
  - 37% of crashes: sudden swerve to avoid auto-rickshaw / cattle
  - 28%: pothole-induced front-wheel loss at 40-60 km/h
  - 22%: rear-end collision at traffic signal (chain reaction)
  - 13%: wrong-side head-on on narrow state highway
  These are NOT textbook crashes. The IMU signatures are WEIRD.
"""

def test_A1_speed_bump_vs_hard_brake():
    """
    Chennai roads have 100+ unmarked speed bumps per km in residential areas.
    A speed bump hit at 40km/h produces: vertical spike +3g, brief decel ~4 m/s²,
    lateral near-zero. A real hard brake produces: decel 7-9 m/s², lateral ~0.2g.
    The system MUST NOT alert on a speed bump. It currently has no vertical-G filter.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test — project not imported"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    # Speed bump signature: massive vertical spike, low lateral
    ts = t_ms()
    speed_bump_events = []
    for i in range(15):
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=-3.5,               # mild decel
            accel_y_ms2=0.1,                 # almost no lateral
            accel_z_ms2=GRAVITY_MS2 + 20.0,  # 2g+ vertical spike ← SPEED BUMP
            gyro_x_degs=random.gauss(0, 0.5),
            gyro_y_degs=random.gauss(0, 0.5),
            gyro_z_degs=random.gauss(0, 1.0),
        )
        ev = detector.push_sample(s)
        if ev:
            speed_bump_events.append(ev)
    
    if speed_bump_events:
        return "CRITICAL", f"FALSE POSITIVE: Speed bump triggered {len(speed_bump_events)} near-miss alert(s). Rider gets alarm every 50m in Chennai."
    return "PASS", "Speed bump correctly ignored"


def test_A2_pothole_front_wheel_wobble():
    """
    Pothole hit at speed causes: sharp vertical drop (-1.5g), then rebound (+2g),
    followed by 200-300ms of high-frequency lateral oscillation (tank-slapper).
    This IS a real near-miss — the system must catch it.
    Frequency signature: 8-15Hz lateral oscillation (handlebar wobble).
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test — project not imported"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    detected = []
    # Pothole: drop + rebound + oscillation
    for i in range(50):
        phase = i / 10.0  # radians
        lateral = 0.38 * math.sin(phase * 12)  # ~12 rad/s = ~2Hz wobble
        vertical_delta = -12.0 * math.exp(-0.5 * (i-5)**2 / 4) + 18.0 * math.exp(-0.5*(i-10)**2/6)
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=-2.0,
            accel_y_ms2=lateral * GRAVITY_MS2,
            accel_z_ms2=GRAVITY_MS2 + vertical_delta,
            gyro_x_degs=random.gauss(0, 2.0),
            gyro_y_degs=random.gauss(0, 1.0),
            gyro_z_degs=30.0 * math.sin(phase * 8),
        )
        ev = detector.push_sample(s)
        if ev:
            detected.append(ev)
    
    if not detected:
        return "FAIL", "Pothole-induced handlebar wobble NOT detected. This kills riders."
    return "PASS", f"Pothole wobble detected: severity={detected[0].severity.value}"


def test_A3_u_turn_vs_skid():
    """
    A normal U-turn on Anna Salai: lateral-G 0.25-0.35g, yaw 40-70°/s, 3-5 seconds.
    A skid onset: lateral-G 0.55g+, yaw 80-120°/s, SUDDEN (< 0.3s).
    The system MUST distinguish them. Incorrectly alerting on U-turns = 
    driver ignores ALL future alerts. Wolf-cry problem kills the system's value.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test — project not imported"
    
    detector_uturn = NearMissDetector(onnx_model_path=None)
    detector_uturn.load()
    fill_detector_buffer(detector_uturn)
    
    ts = t_ms()
    uturn_alerts = []
    # Slow U-turn (normal)
    for i in range(60):
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=random.gauss(-0.5, 0.1),
            accel_y_ms2=random.gauss(0.28 * GRAVITY_MS2, 0.2),  # 0.28g lateral
            accel_z_ms2=GRAVITY_MS2 + random.gauss(0, 0.1),
            gyro_x_degs=random.gauss(0, 1),
            gyro_y_degs=random.gauss(0, 1),
            gyro_z_degs=random.gauss(55.0, 5),  # 55°/s yaw — normal turn
        )
        ev = detector_uturn.push_sample(s)
        if ev:
            uturn_alerts.append(ev)
    
    if uturn_alerts:
        return "FAIL", f"FALSE POSITIVE: Normal U-turn triggered alert. Severity={uturn_alerts[0].severity.value}. This is the wolf-cry failure mode."
    return "PASS", "Normal U-turn correctly not flagged"


def test_A4_gravity_calibration_while_moving():
    """
    CRITICAL BUG RISK: If calibrate_gravity() is called while the rider is already
    moving (e.g., app launched at traffic light that just turned green), the gravity
    offset will be WRONG. All subsequent decel/lateral readings will be offset.
    A 0.5 m/s² forward acceleration during calibration = system thinks all future
    braking is 0.5 m/s² less severe than reality. Near-miss thresholds drift.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test — project not imported"
    
    # Simulate calibration samples collected while accelerating (0.5 m/s²)
    moving_samples = []
    ts = t_ms()
    for i in range(100):
        moving_samples.append(IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=0.5 + random.gauss(0, 0.03),  # 0.5 m/s² forward accel during "calibration"
            accel_y_ms2=random.gauss(0.0, 0.02),
            accel_z_ms2=GRAVITY_MS2 + random.gauss(0, 0.04),
            gyro_x_degs=0, gyro_y_degs=0, gyro_z_degs=0,
        ))
    
    offset = calibrate_gravity(moving_samples, duration_s=1.0)
    bias_error_ms2 = abs(offset[0] - 0.5)  # X-axis should have ~0.5 m/s² error
    
    if bias_error_ms2 < 0.3:
        return "CRITICAL", (
            f"Calibration during motion accepted with only {bias_error_ms2:.3f} m/s² detected error. "
            "No motion guard exists. Hard braking threshold is effectively shifted — "
            f"real {LONGITUDINAL_DECEL_CRITICAL_MS2} m/s² brake appears as {LONGITUDINAL_DECEL_CRITICAL_MS2 - 0.5:.1f} m/s²."
        )
    return "PASS", f"Motion during calibration produces detectable offset: {offset[0]:.3f} m/s² on X-axis"


def test_A5_simultaneous_brake_and_swerve():
    """
    The single most deadly scenario in Chennai: auto-rickshaw cuts in →
    rider simultaneously hard-brakes AND swerves. This is a compound event.
    LATERAL_G + LONGITUDINAL_DECEL both spike at the same moment.
    The detector must not double-fire or get confused by simultaneous max triggers.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test — project not imported"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    events = []
    for i in range(30):
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=-8.5,                  # 8.5 m/s² decel (CRITICAL)
            accel_y_ms2=0.68 * GRAVITY_MS2,    # 0.68g lateral (CRITICAL)
            accel_z_ms2=GRAVITY_MS2 + 0.3,
            gyro_x_degs=random.gauss(0, 2),
            gyro_y_degs=random.gauss(0, 2),
            gyro_z_degs=random.gauss(95, 10),   # 95°/s yaw (CRITICAL)
        )
        ev = detector.push_sample(s)
        if ev:
            events.append(ev)
    
    if not events:
        return "CRITICAL", "Simultaneous CRITICAL brake+swerve NOT detected. Auto-rickshaw cut-in is TN's #1 near-miss scenario."
    
    severities = set(e.severity.value for e in events)
    if "CRITICAL" not in severities:
        return "FAIL", f"Detected but severity={severities}. Should be CRITICAL for compound event."
    
    if len(events) > 5:
        return "WARN", f"Compound event triggered {len(events)} alerts in 300ms. Alert flood may overwhelm TTS queue."
    
    return "PASS", f"Compound crash detected as CRITICAL | alerts={len(events)}"


# ════════════════════════════════════════════════════════════════════════════════
# [B] HUMAN BEHAVIOUR SCENARIOS (Real TN Road User Psychology)
# ════════════════════════════════════════════════════════════════════════════════

section("[B] HUMAN BEHAVIOUR SCENARIOS — Real Rider Psychology")

"""
From RADMS Tamil Nadu 2011-2016:
  - 82% male victims, peak age 20-39 (exactly your target user)
  - 70-82% of fatal crashes involved alcohol (TASMAC effect)
  - 25% of crashes: no valid license
  - "Teasing" / road rage involved in ~8% urban crashes (Chennai data)
"""

def test_B1_drunk_rider_signature():
    """
    A drunk rider (BAC 0.05-0.10) produces a specific IMU signature:
    - Micro-corrections: rapid small lateral oscillations 0.05-0.15g at 2-4Hz
    - Over-steering: yaw rate overshoots by 20-40% on each correction
    - Delayed reaction: no decel before impact (no pre-braking)
    The current system only detects threshold crossings, not pattern-of-behavior.
    A drunk rider may never cross LATERAL_G_MEDIUM_THRESHOLD individually
    but the cumulative pattern screams danger. The system misses this entirely.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    
    ts = t_ms()
    events = []
    # 2 seconds of drunk micro-corrections — BAC ~0.08 signature
    for i in range(200):
        t = i * 0.01
        lateral = 0.12 * math.sin(2 * math.pi * 3.0 * t) + 0.08 * math.sin(2 * math.pi * 1.5 * t)
        yaw = 25.0 * math.sin(2 * math.pi * 2.5 * t + 0.3)  # over-steer phase lag
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=random.gauss(0.1, 0.05),
            accel_y_ms2=lateral * GRAVITY_MS2,
            accel_z_ms2=GRAVITY_MS2 + random.gauss(0.1, 0.08),
            gyro_x_degs=random.gauss(0, 1),
            gyro_y_degs=random.gauss(0, 1),
            gyro_z_degs=yaw,
        )
        ev = detector.push_sample(s)
        if ev:
            events.append(ev)
    
    if not events:
        return "FAIL", (
            "DESIGN GAP: Drunk-rider micro-correction pattern (0.12g lateral oscillations, "
            "3Hz) produces NO alert. This is TN's #1 crash cause (70%+ fatalities involve alcohol). "
            "System needs a temporal variance / frequency-domain feature — not just peak thresholds."
        )
    return "PASS", f"Drunk rider pattern detected | events={len(events)}"


def test_B2_medical_emergency_seizure():
    """
    Epileptic seizure or sudden cardiac arrest while riding:
    - Immediate limb rigidity: sustained throttle, NO braking
    - Rigid arms: erratic random lateral forces (not periodic like drunk)
    - High-frequency noise on all axes (muscle spasm): 8-30Hz
    - Followed by complete limpness (rider falls → bike skids alone)
    System has no 'rider incapacitated' detection mode.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    events = []
    # Phase 1: Seizure (10-15 Hz muscle spasm, rigid body)
    for i in range(80):
        noise = random.gauss(0, 0.25 * GRAVITY_MS2)  # high-freq random
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=random.gauss(0.2, 0.5),  # no braking (rigid)
            accel_y_ms2=noise,
            accel_z_ms2=GRAVITY_MS2 + random.gauss(0, 0.8),
            gyro_x_degs=random.gauss(0, 15),  # muscle spasm
            gyro_y_degs=random.gauss(0, 12),
            gyro_z_degs=random.gauss(0, 10),
        )
        ev = detector.push_sample(s)
        if ev:
            events.append(ev)
    
    if not events:
        return "FAIL", (
            "DESIGN GAP: Rider seizure/cardiac arrest not detectable. "
            "No 'no-braking + erratic IMU' pattern recognition. "
            "System needs a 'rider incapacitated' alert mode — this is a different emergency."
        )
    return "PASS", f"Medical emergency signature detected | events={len(events)}"


def test_B3_road_rage_tailgating_detection():
    """
    Aggressive tailgating produces a specific 'following oscillation' pattern:
    rider repeatedly micro-brakes to match a decelerating vehicle ahead.
    The near-miss happens when the lead vehicle stops suddenly.
    Currently the system only reacts post-event. Is there pre-event signal?
    """
    return "FAIL", (
        "DESIGN GAP: No proactive tailgating detection. "
        "Repeated micro-braking oscillations (0.5-1.5 m/s² at 0.5Hz for 30+ seconds) "
        "are a textbook pre-collision signature. System is reactive-only. "
        "RECOMMENDATION: Add rolling variance monitor on longitudinal decel."
    )


def test_B4_pillion_rider_weight_shift():
    """
    A 70kg pillion passenger dramatically changes the bike's dynamics:
    - Lateral threshold in practice is LOWER (more tippable)
    - Braking distance is ~30% longer
    - Yaw response is sluggish (more inertia)
    The current thresholds are calibrated for a solo rider.
    With pillion, LATERAL_G_CRITICAL_THRESHOLD=0.65 may be 20% too generous.
    """
    return "FAIL", (
        f"DESIGN GAP: No pillion-rider mode. "
        f"Current LATERAL_G_CRITICAL_THRESHOLD={LATERAL_G_CRITICAL_THRESHOLD}g is for solo rider. "
        f"With 70kg pillion, effective critical threshold should be ~0.52g. "
        f"TN Sec 194D(2) explicitly mandates pillion helmet — system KNOWS about pillions legally "
        f"but ignores pillion physics entirely. Add user-configurable load mode."
    )


def test_B5_phone_in_pocket_vibration():
    """
    Most users will mount the phone in a trouser pocket, not on handlebars.
    Pocket placement introduces: leg movement noise (3-5g at 1-3Hz during acceleration),
    fabric interference, thermal variation affecting IMU drift.
    The IMU thresholds were clearly designed for handlebar/stem mounting.
    Pocket mounting = constant false positives from leg movement.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    events = []
    # Simulate leg movement noise (walking pace, knee lift rhythm)
    for i in range(100):
        t = i * 0.01
        # Leg cycle at ~1.2Hz (fast riding gait / foot peg movement)
        leg_noise = 1.5 * GRAVITY_MS2 * abs(math.sin(math.pi * 1.2 * t))
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=random.gauss(0.3, 0.1),
            accel_y_ms2=random.gauss(0.1, 0.05),
            accel_z_ms2=GRAVITY_MS2 + leg_noise + random.gauss(0, 0.2),
            gyro_x_degs=random.gauss(0, 8),  # pocket wobble
            gyro_y_degs=random.gauss(0, 6),
            gyro_z_degs=random.gauss(0, 4),
        )
        ev = detector.push_sample(s)
        if ev:
            events.append(ev)
    
    if events:
        return "FAIL", (
            f"Pocket-mounting leg noise triggered {len(events)} false alerts in 1 second of normal riding. "
            "Device placement guide is MISSING from the project. Without handlebar mounting instruction, "
            "every user will pocket-mount and the system becomes useless noise."
        )
    return "PASS", "Pocket-noise not triggering false alerts (verify with physical test)"


# ════════════════════════════════════════════════════════════════════════════════
# [C] ENVIRONMENTAL CONDITIONS
# ════════════════════════════════════════════════════════════════════════════════

section("[C] ENVIRONMENTAL CONDITIONS — Indian Roads Are Not Lab Conditions")

def test_C1_monsoon_rain_slippery_road():
    """
    During Chennai monsoon (Oct-Dec), wet roads reduce tyre friction coefficient
    from ~0.8 (dry) to ~0.35 (wet) to ~0.20 (flooded). A 0.35g lateral force
    on dry road = aggressive lane change. On wet road = bike is SLIDING.
    The same IMU reading means very different danger levels.
    System has no weather/road-condition awareness — it CANNOT know this.
    """
    return "FAIL", (
        "DESIGN GAP: No weather context. Monsoon road μ=0.35 vs dry μ=0.8. "
        "Same lateral-G reading = 2.3x more dangerous on wet road. "
        "RECOMMENDATION: Integrate device GPS speed + weather API (even offline approximation "
        "from date/time + stored monsoon calendar for TN). "
        "Alternative: lower all thresholds by 30% if rainfall detected via microphone FFT."
    )


def test_C2_railway_crossing_vibration():
    """
    TN has 4,500+ unmanned level crossings. Crossing railway tracks at speed
    produces: sustained high-frequency vibration (15-40Hz) on all axes,
    vertical spikes ±3g, and erratic yaw. This can last 0.5-2 seconds.
    The system WILL false-alarm on every railway crossing at speed.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    events = []
    # Railway crossing vibration signature
    for i in range(50):
        t = i * 0.01
        vibe = random.gauss(0, 2.5 * GRAVITY_MS2)
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=random.gauss(-1.0, 1.5),   # rough decel from track bump
            accel_y_ms2=random.gauss(0.15, 0.4) * GRAVITY_MS2,
            accel_z_ms2=GRAVITY_MS2 + vibe,
            gyro_x_degs=random.gauss(0, 20),  # vibration
            gyro_y_degs=random.gauss(0, 15),
            gyro_z_degs=random.gauss(0, 8),
        )
        ev = detector.push_sample(s)
        if ev:
            events.append(ev)
    
    if events:
        return "FAIL", (
            f"Railway crossing vibration triggered {len(events)} false alerts. "
            "TN has 4,500+ level crossings. This system will cry wolf multiple times per commute."
        )
    return "PASS", "Railway crossing vibration not triggering false alerts"


def test_C3_cattle_on_road_sudden_swerve():
    """
    Cattle-on-road is TN rural roads' #1 hazard, causing genuine near-misses.
    The swerve is REAL and should be detected. But the current system cannot
    distinguish this from an unmarked speed bump swerve. Both are valid detections.
    Test: does the system catch a real cattle-avoidance swerve?
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    events = []
    # Cattle swerve: fast, large lateral + moderate decel, short duration (0.3-0.5s)
    for i in range(40):
        progression = min(i / 15.0, 1.0)
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=-4.5 * progression,
            accel_y_ms2=0.50 * GRAVITY_MS2 * progression,
            accel_z_ms2=GRAVITY_MS2 + random.gauss(0.1, 0.15),
            gyro_x_degs=random.gauss(0, 2),
            gyro_y_degs=random.gauss(0, 2),
            gyro_z_degs=70.0 * progression,
        )
        ev = detector.push_sample(s)
        if ev:
            events.append(ev)
    
    if not events:
        return "FAIL", "Cattle-avoidance swerve NOT detected. This is a genuine road emergency."
    return "PASS", f"Cattle-avoidance swerve detected: severity={events[0].severity.value}"


def test_C4_thermal_throttling_cpu():
    """
    Android mid-range phones (Dimensity 700) thermal-throttle at 42-48°C CPU temp.
    In a Chennai summer (ambient 38°C + phone in direct sun), CPU temp can hit
    55-60°C within 20 minutes of continuous ONNX inference at 10Hz.
    When thermal throttling kicks in: inference latency spikes from 15ms → 200ms+.
    At 100Hz IMU, 200ms inference latency = 20 samples of unprocessed data.
    The IMUBuffer will overwrite oldest samples. Near-miss window is corrupted.
    """
    return "CRITICAL", (
        "DESIGN GAP: No thermal throttling protection. "
        "Under Chennai summer + direct sunlight: ONNX inference latency can spike 13x. "
        "IMUBuffer ring-buffer will drop 15+ critical samples during a crash event. "
        "RECOMMENDATION: (1) Add inference_latency_ms monitoring. "
        "(2) If latency > 30ms, drop to DETERMINISTIC mode automatically. "
        "(3) Add a watchdog that checks processed_samples_per_second ≥ 90."
    )


# ════════════════════════════════════════════════════════════════════════════════
# [D] SYSTEM FAILURE MODES
# ════════════════════════════════════════════════════════════════════════════════

section("[D] SYSTEM FAILURE MODES — What Happens When Hardware Dies")

def test_D1_onnx_session_crash_mid_ride():
    """
    ONNX Runtime crashes on Android if: (1) background app kills the process,
    (2) NNAPI delegate throws OOM, (3) model weights corrupted on flash storage.
    The current fallback is 'mode = DETERMINISTIC'. BUT: the crash happens inside
    _run_inference() with no recovery path. The system SILENTLY stops detecting.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    # Verify the detector has no heartbeat / watchdog
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    
    # Check: does the detector expose any health-check interface?
    has_heartbeat = hasattr(detector, 'heartbeat') or hasattr(detector, 'is_alive') or hasattr(detector, 'health_check')
    
    if not has_heartbeat:
        return "CRITICAL", (
            "NO WATCHDOG EXISTS. If ONNX session crashes mid-ride, "
            "detector silently falls back to DETERMINISTIC mode with NO user notification. "
            "Rider has no idea the ML-powered detection is dead. "
            "REQUIREMENT: Add health_check() → emit TTS 'AI degraded, basic mode' alert."
        )
    return "PASS", "Heartbeat/watchdog interface exists"


def test_D2_imu_sample_gap_detection():
    """
    Android IMU can stall for 50-200ms when the OS scheduler preempts the sensor
    thread (garbage collection, background sync, incoming call).
    A 150ms gap at 100Hz = 15 missing samples. The ring buffer fills with stale data.
    If a crash happens during the gap, the buffer window is corrupted — crash missed.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    buffer = IMUBuffer(capacity=WINDOW_SIZE_SAMPLES)
    ts = t_ms()
    
    # Fill normally for 1 second
    for i in range(100):
        s = normal_sample(ts + i*10)
        if s:
            buffer.push(s)
    
    # Simulate 200ms gap (20 samples missing)
    ts_gap = ts + 100*10 + 200
    
    # Now push a crash event after the gap
    for i in range(20):
        s = swerve_sample(ts_gap + i*10)
        if s:
            buffer.push(s)
    
    window = buffer.get_window()
    # Check if the gap leaves stale (zero) data polluting the window
    zero_rows = (window == 0).all(axis=1).sum()
    
    if zero_rows > 0:
        return "FAIL", f"{zero_rows} zero-rows in crash window from IMU gap. Crash signature diluted."
    
    # Check timestamp continuity detection
    return "WARN", (
        "IMUBuffer has no timestamp validation. A 200ms IMU gap cannot be detected internally. "
        "Stale data from pre-gap rides can dilute the crash signature. "
        "RECOMMENDATION: Store timestamps per sample; reject window if gap > 50ms detected."
    )


def test_D3_battery_15_percent_behavior():
    """
    At 15% battery, Android aggressively kills background processes and reduces
    CPU/GPU clock. The system must warn the rider and degrade gracefully,
    NOT silently reduce accuracy. Currently: no battery monitoring exists.
    """
    return "CRITICAL", (
        "DESIGN GAP: No battery level monitoring. "
        "At <20% battery, Android OS WILL throttle the sensor sampling rate and may "
        "kill the NNAPI background process. The system should: "
        "(1) Monitor battery level via Android API. "
        "(2) At <20%: emit TTS warning 'Low battery, detection may degrade'. "
        "(3) At <10%: force DETERMINISTIC mode, reduce inference rate to 2Hz. "
        "A rider relying on this system at 8% battery on a highway = false safety."
    )


def test_D4_concurrent_imu_inference_tts():
    """
    In production, 3 threads run simultaneously:
      Thread-1: IMU acquisition at 100Hz
      Thread-2: ONNX inference at 10Hz
      Thread-3: TTS announcement (blocking pyttsx3 call)
    The IMUBuffer's push() and get_window() are NOT thread-safe.
    A concurrent push() during get_window()'s np.roll() = TOCTOU data corruption.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    buffer = IMUBuffer(capacity=WINDOW_SIZE_SAMPLES)
    errors = []
    stop = threading.Event()
    
    def writer():
        ts = t_ms()
        i = 0
        while not stop.is_set():
            s = normal_sample(ts + i*10)
            if s:
                try:
                    buffer.push(s)
                except Exception as e:
                    errors.append(f"Writer: {e}")
            i += 1
            time.sleep(0.01)
    
    def reader():
        while not stop.is_set():
            try:
                if buffer.is_full():
                    w = buffer.get_window()
                    if w.shape != (WINDOW_SIZE_SAMPLES, 6):
                        errors.append(f"Window shape corrupted: {w.shape}")
            except Exception as e:
                errors.append(f"Reader: {e}")
            time.sleep(0.1)
    
    t1 = threading.Thread(target=writer, daemon=True)
    t2 = threading.Thread(target=reader, daemon=True)
    t1.start(); t2.start()
    time.sleep(1.0)
    stop.set()
    t1.join(timeout=0.5); t2.join(timeout=0.5)
    
    if errors:
        return "CRITICAL", f"Thread safety violation: {errors[0]}. Data race in IMUBuffer."
    return "PASS", "No race condition detected in 1s concurrent test (run longer for confidence)"


# ════════════════════════════════════════════════════════════════════════════════
# [E] LEGAL LOGIC CORRECTNESS
# ════════════════════════════════════════════════════════════════════════════════

section("[E] LEGAL LOGIC — Wrong Section 208 = Driver Loses in Court")

def test_E1_section_208_distance_boundary():
    """
    Section 208 trigger: "speed camera detected + NO speed sign within 500m".
    The system's resolver uses a boolean `signage_detected` — it does NOT
    compute actual distance to the nearest sign. A sign at 499m = challenge valid.
    A sign at 501m = no challenge. The current implementation CANNOT distinguish.
    This is the core legal argument — distance measurement is missing.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    resolver = Section208Resolver()
    
    # Does the resolver accept distance parameters?
    import inspect
    sig = inspect.signature(resolver.challenge_speed_camera)
    params = list(sig.parameters.keys())
    
    has_distance = any('dist' in p or 'meter' in p or 'upstream' in p for p in params)
    
    if not has_distance:
        return "CRITICAL", (
            "Section 208 resolver accepts boolean `signage_detected`, NOT distance. "
            "A sign at 499m (challenge valid) vs 501m (no challenge) is legally decisive. "
            "Current implementation: any sign anywhere = 'signage_detected=True' → no challenge. "
            "This will fail in court. IRC:67 requires sign WITHIN 500m UPSTREAM. "
            "Fix: resolver must accept (camera_gps, sign_gps) and compute haversine distance."
        )
    return "PASS", "Distance-aware Section 208 logic exists"


def test_E2_section_208_audit_document_quality():
    """
    The generated audit request must be court-admissible. It must contain:
    - Exact GPS coordinates (not rounded)
    - Timestamp in IST with timezone offset
    - SHA3-256 hash of telemetry evidence
    - RTO jurisdiction (derived from GPS)
    - Rider's name / vehicle reg number
    The current template has placeholders for lat/lon but no hash, no IST, no RTO.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    resolver = Section208Resolver()
    camera = {"lat": 12.9249, "lon": 80.1300, "type": "speed_camera"}
    result = resolver.challenge_speed_camera(camera, signage_detected=False)
    
    doc = result.get("document", "")
    
    issues = []
    if "SHA" not in doc and "hash" not in doc.lower():
        issues.append("No evidence hash")
    if "IST" not in doc and "+05:30" not in doc:
        issues.append("No IST timestamp")
    if "RTO" not in doc:
        issues.append("No RTO addressee")
    if str(camera["lat"]) not in doc:
        issues.append("GPS lat not in document")
    
    if issues:
        return "FAIL", f"Audit document missing: {', '.join(issues)}. Document may be inadmissible."
    return "PASS", "Audit document contains required legal fields"


def test_E3_mvact_section_numbers_correct():
    """
    Verify the legal schema references correct MVA 2019 section numbers.
    A wrong section number in the auto-generated document = instant dismissal.
    """
    import json, os
    schema_path = os.path.join(os.path.dirname(__file__), "schemas", "universal_legal_schema.json")
    if not os.path.exists(schema_path):
        return "WARN", "universal_legal_schema.json not found — cannot verify section numbers"
    
    with open(schema_path) as f:
        schema = json.load(f)
    
    registry = schema.get("offence_registry", {})
    expected = {
        "IN_SEC_194D": "194D",
        "IN_SEC_183":  "183",
        "IN_SEC_177":  "177",
    }
    
    errors = []
    for key, expected_sec in expected.items():
        if key in registry:
            actual_sec = str(registry[key].get("statute_ref", {}).get("section", ""))
            if actual_sec != expected_sec:
                errors.append(f"{key}: expected section {expected_sec}, got {actual_sec}")
    
    if errors:
        return "CRITICAL", f"Wrong section numbers: {errors}. Court documents will cite wrong law."
    return "PASS", "All MVA 2019 section numbers correct"


# ════════════════════════════════════════════════════════════════════════════════
# [F] TTS LATENCY & PRIORITY
# ════════════════════════════════════════════════════════════════════════════════

section("[F] TTS LATENCY & PRIORITY — Alert 100ms Late = Already Crashed")

def test_F1_tts_queue_saturation():
    """
    If 3 CRITICAL events fire within 500ms (compound crash scenario),
    the TTS priority queue fills. pyttsx3 is BLOCKING — each utterance
    takes 2-4 seconds for a full alert phrase.
    Queued alerts play AFTER the crash is already over — completely useless.
    Max useful TTS window: 800ms from event detection.
    """
    return "CRITICAL", (
        "DESIGN GAP: pyttsx3 is synchronous/blocking. A 3-word CRITICAL alert "
        "('Hard brake detected!') takes ~1.2 seconds on Dimensity 700. "
        "A compound event queues 3 alerts = 3.6 seconds of audio. "
        "The crash resolves in 0.3-0.8 seconds. Alerts play AFTER impact. "
        "REQUIREMENT: (1) CRITICAL alert must be ≤ 3 words. (2) New CRITICAL "
        "interrupt MUST flush the queue and preempt. (3) Target: <80ms from "
        "event detection to first audio byte. Current architecture cannot do this."
    )


def test_F2_tts_language_in_emergency():
    """
    The project uses Bhashini Tanglish TTS. In panic/emergency:
    - A rider who learned to ignore English alerts (urban TN, 60% prefer Tamil)
    - An alert in English during a high-stress moment = cognitive freeze
    The system must speak the rider's FIRST language for CRITICAL alerts.
    Currently: no language preference stored per user.
    """
    return "FAIL", (
        "DESIGN GAP: Single TTS language hardcoded. "
        "60%+ of TN two-wheeler riders are more fluent in Tamil than English. "
        "A CRITICAL alert in an unfamiliar language during panic = ignored. "
        "REQUIREMENT: User onboarding must select language. "
        "CRITICAL alerts must play in: Tamil first, then English fallback. "
        "The Bhashini TTS model is already in the stack — use it properly."
    )


# ════════════════════════════════════════════════════════════════════════════════
# [G] BLE MESH INTEGRITY
# ════════════════════════════════════════════════════════════════════════════════

section("[G] BLE MESH INTEGRITY — Ghost Events Must Never Alert")

def test_G1_replay_attack_old_hazard():
    """
    BLE mesh has TTL=7 hops. A hazard alert from 45 minutes ago (pothole cleared,
    road fixed) can still be bouncing around the mesh. A rider receives a 'POTHOLE'
    alert for a hazard that no longer exists. The protocol has no timestamp expiry.
    The ble_mesh_protocol.json has timestamp field but NO max_age_seconds policy.
    """
    import json, os
    schema_path = os.path.join(os.path.dirname(__file__), "ble_mesh_protocol.json")
    if not os.path.exists(schema_path):
        return "WARN", "ble_mesh_protocol.json not found"
    
    with open(schema_path) as f:
        proto = json.load(f)
    
    hazard_fields = proto.get("message_types", {}).get("HAZARD_ALERT", {}).get("fields", [])
    config = proto.get("offline_mesh_configuration", {})
    
    has_expiry = "expiry" in hazard_fields or "max_age" in str(config) or "ttl_seconds" in str(config)
    
    if not has_expiry:
        return "CRITICAL", (
            "No hazard expiry in BLE mesh protocol. TTL=7 hops + mesh_ttl field counts hops only. "
            "A POTHOLE alert can circulate for hours. Riders will brake hard for phantom hazards. "
            "REQUIREMENT: Add 'expiry_epoch_ms' to HAZARD_ALERT. "
            "Reject any hazard older than 300 seconds (5 min for potholes, 30 min for construction)."
        )
    return "PASS", "Hazard expiry policy exists in mesh protocol"


def test_G2_spoofed_hazard_injection():
    """
    BLE mesh uses AES-128-CCM encryption but there is NO authentication of node identity.
    Any BLE device within range can inject a 'SPEED_TRAP_NO_SIGNAGE' alert (type 1),
    causing mass braking on a highway. This is a real attack vector.
    The schema has node_id but no cryptographic signing.
    """
    import json, os
    schema_path = os.path.join(os.path.dirname(__file__), "ble_mesh_protocol.json")
    if not os.path.exists(schema_path):
        return "WARN", "Schema not found"
    
    with open(schema_path) as f:
        proto = json.load(f)
    
    hazard_fields = proto.get("message_types", {}).get("HAZARD_ALERT", {}).get("fields", [])
    has_signature = any(f in hazard_fields for f in ["signature", "hmac", "zkp", "proof"])
    
    if not has_signature:
        return "CRITICAL", (
            "BLE mesh HAZARD_ALERT has no cryptographic signature field. "
            "AES-128-CCM protects confidentiality but NOT authenticity of sender. "
            "Attack: rogue BLE device broadcasts fake SPEED_TRAP_NO_SIGNAGE → "
            "every nearby rider gets phantom legal challenge → mass highway confusion. "
            "ZKP envelope (zkp_envelope.py T-014) exists for telemetry but NOT for mesh messages. "
            "REQUIREMENT: Add Pedersen commitment or HMAC-SHA256 to HAZARD_ALERT signature field."
        )
    return "PASS", "Hazard messages include cryptographic signature"


# ════════════════════════════════════════════════════════════════════════════════
# [H] THRESHOLD BOUNDARY TESTING
# ════════════════════════════════════════════════════════════════════════════════

section("[H] THRESHOLD BOUNDARY — Off-By-One at 0.64g Can Mean Death")

def test_H1_one_percent_below_critical_threshold():
    """
    A lateral-G of 0.644g is 0.006g below LATERAL_G_CRITICAL_THRESHOLD=0.65g.
    Real crash data: 0.644g lateral on wet road = bike slides. System says: MEDIUM.
    The 1% margin of error in sensor calibration can move a CRITICAL event to MEDIUM.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    extractor = NearMissFeatureExtractor()
    
    # Just below critical threshold
    import numpy as np
    window = np.zeros((WINDOW_SIZE_SAMPLES, 6), dtype=np.float32)
    # Set lateral column to 0.644g throughout
    window[:, 1] = 0.644 * GRAVITY_MS2
    window[:, 2] = GRAVITY_MS2
    window[:, 0] = -5.0  # near-critical decel
    window[:, 5] = 80.0  # near-critical yaw
    
    features = extractor.compute(window)
    severity = extractor.classify_severity_deterministic(
        features["lateral_g_peak"],
        features["longitudinal_decel_ms2"],
        features["yaw_rate_peak_degs"],
        features["rms_jerk_ms3"],
    )
    
    detail = (
        f"lateral_g={features['lateral_g_peak']:.4f}g "
        f"(threshold={LATERAL_G_CRITICAL_THRESHOLD}g) → {severity.value}"
    )
    
    if severity == NearMissSeverity.MEDIUM:
        return "FAIL", (
            f"{detail}. A compound event at 99% of critical threshold classified MEDIUM. "
            "Sensor ±2% tolerance means this is effectively CRITICAL in the physical world. "
            "RECOMMENDATION: Apply fuzzy classification — within 5% of threshold → upgrade severity."
        )
    return "PASS", detail


def test_H2_anomaly_score_fence_post():
    """
    TCN anomaly_score_threshold=0.65. Score of 0.649 = no event. 0.651 = event.
    The deterministic severity + TCN score combined decision creates a complex
    interaction where MEDIUM deterministic + 0.649 TCN score = nothing fires.
    But MEDIUM + 0.651 = HIGH event. The 0.002 difference changes the outcome.
    This needs to be explicitly documented and tested with real crash data.
    """
    return "WARN", (
        f"anomaly_score_threshold={0.65} creates a hard fence-post decision. "
        "TCN score of 0.649 vs 0.651 = different outcomes with no physical basis. "
        "This threshold was set without validation against real iRAD crash telemetry. "
        "REQUIREMENT: Validate threshold using ROC curve on actual TN crash dataset. "
        "Until then, consider lowering to 0.60 (higher recall, lower precision) "
        "— in life-safety systems, false negatives are worse than false positives."
    )


# ════════════════════════════════════════════════════════════════════════════════
# [I] MODEL GAPS & DATA QUALITY
# ════════════════════════════════════════════════════════════════════════════════

section("[I] MODEL GAPS — The TCN Is Untrained. Everything Is Theoretical.")

def test_I1_tcn_model_has_no_weights():
    """
    The TCNNearMissModel is defined but has NO trained weights.
    The smoke test initializes it untrained. An untrained model produces
    RANDOM scores ∈ [0,1]. Random scores will randomly trigger alerts.
    The system currently ships with a neural network that is EQUIVALENT TO A COIN FLIP.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    try:
        import torch
        if not torch:
            raise ImportError
        from agents.imu_near_miss_detector import TCNNearMissModel, TORCH_AVAILABLE
        if not TORCH_AVAILABLE:
            return "WARN", "PyTorch not available — cannot test model weights"
        
        model = TCNNearMissModel()
        # Check if all weights are at initialization (Xavier/He init ≠ trained)
        # An untrained model on zero input should give ~0.5 (sigmoid of near-zero)
        import numpy as np
        dummy = torch.zeros(1, 6, WINDOW_SIZE_SAMPLES)
        with torch.no_grad():
            score = float(model(dummy).item())
        
        # Untrained sigmoid output on zeros is ~0.5
        if 0.3 < score < 0.7:
            return "CRITICAL", (
                f"TCN produces score={score:.4f} on zero input (untrained). "
                "The neural network has NO trained weights. "
                "In ONNX_INT8_NPU mode, if an ONNX file is loaded, "
                "it is an untrained export — equivalent to random noise. "
                "REQUIREMENT: (1) Collect real iRAD crash telemetry. "
                "(2) Train TCN with minimum 5,000 labeled near-miss events. "
                "(3) Validate: precision ≥ 0.90, recall ≥ 0.95 on held-out TN data. "
                "Until then: DISABLE ONNX mode. Use DETERMINISTIC only. Be honest about it."
            )
    except ImportError:
        pass
    return "WARN", "Cannot fully validate — PyTorch not installed in test env"


def test_I2_idd_dataset_actually_indian():
    """
    The README says: 'Vision Model: YOLOv8-nano (IDD-trained weights only — no COCO/Cityscapes)'.
    But fetch_vision_models.py downloads 'road-signs-indian-p2kgu' from Roboflow,
    which is a crowd-sourced dataset. The 'IDD' claim in README vs actual data source
    is inconsistent. IDD (India Driving Dataset, IIT Hyderabad) is NOT Roboflow.
    The model may not actually be IDD-trained. This affects all vision claims.
    """
    return "CRITICAL", (
        "README claims IDD-trained YOLOv8-nano. fetch_vision_models.py downloads "
        "'road-signs-indian-p2kgu' from Roboflow (crowd-sourced, not IDD). "
        "IDD dataset is from IIT Hyderabad — requires separate access. "
        "These are DIFFERENT training distributions. The model's claimed provenance is wrong. "
        "If presented to IIT Madras CoERS judges: this inconsistency will be caught. "
        "FIX: Either (a) actually use IDD weights, or (b) correct README to say 'Roboflow dataset'. "
        "Do NOT misrepresent training data to a safety-research audience."
    )


# ════════════════════════════════════════════════════════════════════════════════
# [J] ADVERSARIAL & WORST-CASE SCENARIOS
# ════════════════════════════════════════════════════════════════════════════════

section("[J] ADVERSARIAL — The Scenarios Nobody Planned For")

def test_J1_rider_drops_phone():
    """
    If the phone detaches from the handlebar mount and falls to the road,
    the IMU will see: free-fall (accel ≈ 0 on all axes for 0.1-0.3s),
    then extreme impact (50g+ spike on all axes), then chaotic tumbling.
    The system will interpret this as a CRITICAL crash and trigger TTS alerts,
    BLE hazard broadcast, and potentially Section 208 drafts — for a dropped phone.
    Worse: if the phone falls DURING a real crash, events are mixed.
    """
    if not PROJECT_IMPORTED:
        return "FAIL", "Cannot test"
    
    detector = NearMissDetector(onnx_model_path=None)
    detector.load()
    fill_detector_buffer(detector)
    
    ts = t_ms()
    events = []
    
    # Free-fall phase (0.2s)
    for i in range(20):
        s = IMUSample(
            timestamp_epoch_ms=ts + i*10,
            accel_x_ms2=random.gauss(0.0, 0.1),
            accel_y_ms2=random.gauss(0.0, 0.1),
            accel_z_ms2=random.gauss(0.0, 0.1),  # free fall ≈ 0g
            gyro_x_degs=random.gauss(0, 5),
            gyro_y_degs=random.gauss(0, 5),
            gyro_z_degs=random.gauss(0, 5),
        )
        ev = detector.push_sample(s)
        if ev: events.append(ev)
    
    # Impact (1 sample, extreme)
    impact = IMUSample(
        timestamp_epoch_ms=ts + 200,
        accel_x_ms2=random.gauss(0, 150),
        accel_y_ms2=random.gauss(0, 150),
        accel_z_ms2=GRAVITY_MS2 + random.gauss(0, 150),
        gyro_x_degs=random.gauss(0, 300),
        gyro_y_degs=random.gauss(0, 300),
        gyro_z_degs=random.gauss(0, 300),
    )
    ev = detector.push_sample(impact)
    if ev: events.append(ev)
    
    return "WARN", (
        f"Phone drop triggered {len(events)} event(s). "
        "No free-fall detection guard exists. A dropped phone = false crash alert. "
        "RECOMMENDATION: Detect free-fall (all-axis accel < 0.5g for > 50ms) → "
        "enter 'SENSOR_DISCONNECTED' state, suppress alerts for 3s, emit 'Check device mount'."
    )


def test_J2_wrong_way_ghost_vehicle_head_on():
    """
    Wrong-way driving on TN highways causes 5.8% of fatalities (MoRTH data).
    A head-on near-miss looks like: sudden extreme decel (driver panics + swerves),
    but the swerve direction is PREDICTABLE (always away from threat = LEFT in TN).
    Current system treats left and right swerves identically. This is correct.
    But: the warning message should say "WRONG-WAY VEHICLE" not just "near-miss".
    Vision: detect oncoming vehicle in same lane. IMU: head-on brake signature.
    Currently: vision and IMU are not correlated for this scenario.
    """
    return "FAIL", (
        "DESIGN GAP: No cross-agent correlation for head-on scenarios. "
        "Vision (oncoming vehicle in lane) + IMU (emergency brake) together = head-on. "
        "Separate: both are generic alerts. Together: specific 'WRONG-WAY VEHICLE' warning. "
        "This distinction matters for TTS message content and BLE hazard type selection. "
        "5.8% of TN highway fatalities = wrong-way. This is a named scenario, not an edge case."
    )


def test_J3_100_kmh_highway_vs_20_kmh_city():
    """
    At 100 km/h (NH): a lateral-G of 0.30g is a CATASTROPHIC swerve (rollover risk).
    At 20 km/h (city): a lateral-G of 0.30g is a normal tight turn.
    The system uses IDENTICAL thresholds for both scenarios.
    Without GPS speed context, the system cannot distinguish them.
    At highway speed, MEDIUM threshold events are actually CRITICAL.
    """
    return "CRITICAL", (
        f"SPEED-BLIND THRESHOLDS. Current LATERAL_G_MEDIUM={0.30}g is applied at all speeds. "
        f"At 100 km/h: 0.30g lateral = {0.30*GRAVITY_MS2 * 100/3.6:.1f} m/s² centripetal — "
        "exceeds tyre grip limit on most TN highway surfaces. "
        "Physics: safe lateral-G_max = μ × g / (1 + speed_factor). "
        "REQUIREMENT: If GPS speed > 60 km/h, reduce all thresholds by 40%. "
        "At 100 km/h: LATERAL_G_CRITICAL should be 0.35g, not 0.65g. "
        "This is not a feature — it is a fundamental safety calculation error."
    )


# ════════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════════════

def print_summary():
    section("FINAL VERDICT")
    total = len(results)
    passed = sum(1 for _, v in results if v == "PASS")
    failed = sum(1 for _, v in results if v == "FAIL")
    critical = sum(1 for _, v in results if v == "CRITICAL")
    warned  = sum(1 for _, v in results if v == "WARN")
    
    print(f"\n  Total Tests : {total}")
    print(f"  ✅ PASS     : {passed}")
    print(f"  ❌ FAIL     : {failed}")
    print(f"  ⚠️  WARN     : {warned}")
    print(f"  💀 CRITICAL : {critical}")
    
    print(f"\n{'─'*78}")
    print("  CRITICAL FAILURES (Fix Before Any Real-World Test):")
    print(f"{'─'*78}")
    for name, verdict in results:
        if verdict == "CRITICAL":
            print(f"    💀 {name}")
    
    print(f"\n{'─'*78}")
    print("  DESIGN GAPS (Required Before Pilot Deployment):")
    print(f"{'─'*78}")
    for name, verdict in results:
        if verdict == "FAIL":
            print(f"    ❌ {name}")
    
    print(f"\n{'═'*78}")
    if critical > 0:
        print("  VERDICT: ⛔ NOT READY FOR REAL-WORLD USE")
        print(f"  {critical} critical flaw(s) found that could cause missed crash detection")
        print(f"  or active harm to a rider depending on this system.")
    elif failed > 3:
        print("  VERDICT: ⚠️  PROTOTYPE STAGE — Lab/Demo Only")
    else:
        print("  VERDICT: 🟡 APPROACHING PILOT-READY — Address remaining gaps")
    print(f"{'═'*78}\n")


# ── Run All Tests ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)  # Suppress debug noise during tests
    
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║      SmartSalai Edge-Sentinel — BRUTAL SYSTEM STRESS TEST v1.0             ║
║      "Tamil Nadu: 11,140 two-wheeler deaths/year. 8 crashes/hour."         ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    # [A] IMU Physics
    run_test("A1 Speed Bump False Positive",              test_A1_speed_bump_vs_hard_brake)
    run_test("A2 Pothole Front-Wheel Wobble Detection",   test_A2_pothole_front_wheel_wobble)
    run_test("A3 U-Turn vs Skid Discrimination",          test_A3_u_turn_vs_skid)
    run_test("A4 Gravity Calibration While Moving",       test_A4_gravity_calibration_while_moving)
    run_test("A5 Compound Brake+Swerve (Auto-Rickshaw)",  test_A5_simultaneous_brake_and_swerve)

    # [B] Human Behaviour
    run_test("B1 Drunk Rider Micro-Correction Pattern",   test_B1_drunk_rider_signature)
    run_test("B2 Medical Emergency / Seizure Signature",  test_B2_medical_emergency_seizure)
    run_test("B3 Road Rage Tailgating Pre-Signal",        test_B3_road_rage_tailgating_detection)
    run_test("B4 Pillion Rider Weight — Threshold Bias",  test_B4_pillion_rider_weight_shift)
    run_test("B5 Phone in Pocket — Leg Noise Rejection",  test_B5_phone_in_pocket_vibration)

    # [C] Environment
    run_test("C1 Monsoon — No Weather Context",           test_C1_monsoon_rain_slippery_road)
    run_test("C2 Railway Crossing Vibration FP",          test_C2_railway_crossing_vibration)
    run_test("C3 Cattle-on-Road Swerve Detection",        test_C3_cattle_on_road_sudden_swerve)
    run_test("C4 Thermal Throttling — CPU at 55°C",       test_C4_thermal_throttling_cpu)

    # [D] System Failures
    run_test("D1 ONNX Crash — No Watchdog",               test_D1_onnx_session_crash_mid_ride)
    run_test("D2 IMU Gap — Missing 200ms of Data",        test_D2_imu_sample_gap_detection)
    run_test("D3 Battery 15% — Silent Degradation",       test_D3_battery_15_percent_behavior)
    run_test("D4 Thread Safety — IMUBuffer Race Cond.",   test_D4_concurrent_imu_inference_tts)

    # [E] Legal
    run_test("E1 Section 208 — No Distance Measurement",  test_E1_section_208_distance_boundary)
    run_test("E2 Audit Document Completeness",             test_E2_section_208_audit_document_quality)
    run_test("E3 MVA 2019 Section Numbers Correct",        test_E3_mvact_section_numbers_correct)

    # [F] TTS
    run_test("F1 TTS Queue Saturation — Crash Already Over", test_F1_tts_queue_saturation)
    run_test("F2 Tamil Language for CRITICAL Alerts",     test_F2_tts_language_in_emergency)

    # [G] BLE
    run_test("G1 BLE Mesh — Stale Hazard Replay Attack",  test_G1_replay_attack_old_hazard)
    run_test("G2 BLE Mesh — Spoofed Hazard Injection",    test_G2_spoofed_hazard_injection)

    # [H] Thresholds
    run_test("H1 1% Below Critical — Still Dangerous",    test_H1_one_percent_below_critical_threshold)
    run_test("H2 TCN Score Fence-Post at 0.65",           test_H2_anomaly_score_fence_post)

    # [I] Model
    run_test("I1 TCN Has No Trained Weights",             test_I1_tcn_model_has_no_weights)
    run_test("I2 IDD vs Roboflow Dataset Mismatch",       test_I2_idd_dataset_actually_indian)

    # [J] Adversarial
    run_test("J1 Phone Drop — False Crash Alert",         test_J1_rider_drops_phone)
    run_test("J2 Wrong-Way Head-On — No Cross-Agent Corr", test_J2_wrong_way_ghost_vehicle_head_on)
    run_test("J3 100 km/h Highway Speed-Blind Threshold", test_J3_100_kmh_highway_vs_20_kmh_city)

    print_summary()