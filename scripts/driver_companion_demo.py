#!/usr/bin/env python3
"""Quick demo for the Driver Companion Agent tone and behavior."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.driver_companion_agent import driver_companion


SCENARIOS = [
    ("POTHOLE", "HIGH", "FRONT"),
    ("SPEED_LIMIT", "MEDIUM", "FRONT"),
    ("ACCIDENT", "CRITICAL", "RIGHT"),
    ("LEGAL_SIGN_MISSING", "HIGH", "FRONT"),
]


def main() -> None:
    print("Driver Companion Demo")
    print("=" * 40)
    for hazard, severity, direction in SCENARIOS:
        msg = driver_companion.generate_message(hazard, severity, direction)
        print(f"{hazard:20} | {severity:8} | {direction:6} -> {msg}")


if __name__ == "__main__":
    main()
