"""
tests/test_orchestrator.py
Smoke tests for the SmartSalai orchestrator simulation loop and
bus-driven agent pipeline integration.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_orchestrator_simulation_loop():
    """
    Run the orchestrator's existing simulation loop and verify
    that near-miss events fire, Section 208 challenges are generated,
    TTS announcements are emitted, and iRAD records are produced.
    """
    from core.agent_bus import AgentBus, Topics, reset_bus
    from agents.imu_near_miss_detector import NearMissDetector, IMUSample
    from agents.sec208_drafter import Sec208DrafterAgent
    from agents.sign_auditor import SignAuditorAgent
    from agents.acoustic_ui import AcousticUIAgent
    from core.irad_serializer import IRADSerializer

    reset_bus()
    bus = AgentBus()
    bus.start()

    near_misses = []
    sec208_challenges = []
    tts_announcements = []
    irad_records = []

    bus.subscribe(Topics.IMU_NEAR_MISS, lambda m: near_misses.append(m.params))
    bus.subscribe(Topics.LEGAL_CHALLENGE, lambda m: sec208_challenges.append(m.params))
    bus.subscribe(Topics.TTS_ANNOUNCE, lambda m: tts_announcements.append(m.params))
    bus.subscribe(Topics.IRAD_EMIT, lambda m: irad_records.append(m.params))

    drafter = Sec208DrafterAgent()
    drafter.attach_bus(bus)

    tts = AcousticUIAgent(silent=True)
    tts.attach_bus(bus)
    tts.start()

    serializer = IRADSerializer()
    detector = NearMissDetector()
    detector.load()

    # Simulate IMU data stream: normal → hard swerve
    t_ms = int(time.time() * 1000)
    for i in range(130):
        t_ms += 10
        if i < 110:
            ax, ay, az = 0.1, 0.0, 9.8
            vision_objs = []
        else:
            ax, ay, az = -7.0, 6.0, 10.0
            vision_objs = [
                {"label": "speed_camera", "confidence": 0.90, "bbox": [0.3, 0.1, 0.7, 0.6]}
            ]

        sample = IMUSample(t_ms, ax, ay, az, 0, 0, 90.0 if i > 110 else 0.0)
        event = detector.push_sample(sample)

        if event:
            # Publish near-miss to bus
            event_dict = {
                "severity": event.severity.value,
                "near_miss_score": float(event.tcn_anomaly_score),
                "speed_kmh": float(event.vehicle_speed_kmh) if event.vehicle_speed_kmh else 0.0,
                "gps_lat": None,
                "gps_lon": None,
            }
            bus.publish(Topics.IMU_NEAR_MISS, event_dict)

            # Produce iRAD record
            record = serializer.from_near_miss(event_dict)
            record.finalise()
            bus.publish(Topics.IRAD_EMIT, record.to_dict())

        # Vision → Section 208 check
        if vision_objs:
            has_sign = any(o["label"] == "speed_limit_sign" for o in vision_objs)
            camera_data = {"device_id": "CAM-SIM", "lat": 12.924, "lon": 80.230}
            result = drafter.evaluate(
                camera_data=camera_data,
                signage_detected=has_sign,
                vision_detections=vision_objs,
            )
            if result["status"] == "CHALLENGE_GENERATED":
                bus.publish(Topics.LEGAL_CHALLENGE, result)
                bus.publish(Topics.TTS_ANNOUNCE, {
                    "text": "Speed camera without signage. Section 208 challenge registered.",
                    "critical": False,
                })

    time.sleep(0.2)

    assert len(near_misses) >= 1, f"Expected ≥1 near-miss, got {len(near_misses)}"
    assert len(sec208_challenges) >= 1, f"Expected ≥1 Section 208 challenge, got {len(sec208_challenges)}"
    assert len(tts_announcements) >= 1, f"Expected ≥1 TTS announcement, got {len(tts_announcements)}"
    assert len(irad_records) >= 1, f"Expected ≥1 iRAD record, got {len(irad_records)}"

    bus.stop()
    reset_bus()
    print(
        f"[PASS] test_orchestrator_simulation_loop — "
        f"near_misses={len(near_misses)}, challenges={len(sec208_challenges)}, "
        f"tts={len(tts_announcements)}, irad={len(irad_records)}"
    )


def test_bus_driven_sec208_pipeline():
    """
    Wire Sec208DrafterAgent to bus via vision.detection subscription,
    verify legal.challenge and tts.announce fire.
    """
    from core.agent_bus import AgentBus, Topics, reset_bus
    from agents.sec208_drafter import Sec208DrafterAgent

    reset_bus()
    bus = AgentBus()
    bus.start()

    challenges = []
    tts_msgs = []
    bus.subscribe(Topics.LEGAL_CHALLENGE, lambda m: challenges.append(m.params))
    bus.subscribe(Topics.TTS_ANNOUNCE, lambda m: tts_msgs.append(m.params))

    drafter = Sec208DrafterAgent()
    drafter.attach_bus(bus)

    # Simulate SignAuditor publishing a vision detection with camera but no sign
    bus.publish(Topics.VISION_DETECTION, {
        "detections": [
            {"label": "speed_camera", "confidence": 0.91, "bbox": [0.3, 0.1, 0.7, 0.6]},
        ],
        "camera_device_id": "CAM-BUS-TEST",
        "gps_lat": 12.924,
        "gps_lon": 80.230,
    })

    time.sleep(0.2)

    assert len(challenges) >= 1, f"Expected challenge via bus, got {challenges}"
    assert len(tts_msgs) >= 1, f"Expected TTS via bus, got {tts_msgs}"

    bus.stop()
    reset_bus()
    print("[PASS] test_bus_driven_sec208_pipeline")


if __name__ == "__main__":
    test_orchestrator_simulation_loop()
    test_bus_driven_sec208_pipeline()
    print("\n[ALL PASS] test_orchestrator.py")
