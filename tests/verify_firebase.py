#!/usr/bin/env python3
"""
SmartSalai Edge-Sentinel — Firebase Connectivity Tester (v1.0)
Verifies cloud sync readiness by performing a 'Dry Run' telemetry push.
"""

import os
import sys
import time
from dotenv import load_dotenv
from pathlib import Path

# Ensure local 'core' is importable
sys.path.insert(0, str(Path(__file__).parent))
from core.firebase_client import fb_client

def test_connection():
    print("🛰️  SmartSalai Cloud Connectivity Pulse (Firebase)...")
    
    # 1. Check for Config
    proj_id = os.getenv("FIREBASE_PROJECT_ID")
    if not proj_id:
        print("❌ ERROR: FIREBASE_PROJECT_ID not found in .env.")
        return
    
    print(f"🔍 Testing project: {proj_id}")
    
    # 2. Check Client Initialization
    if not fb_client.is_connected():
        print("❌ ERROR: Firebase Client failed to initialize. Check your credentials path.")
        return
    
    print("✅ Firebase Client initialized successfully.")
    
    # 3. Perform 'Dry Run' Telemetry Push
    print("📡 Attempting 'Dry Run' telemetry push (SENTINEL_VERIFY_NODE)...")
    try:
        fb_client.push_telemetry("SENTINEL_VERIFY_NODE", {
            "status": "VERIFICATION_SUCCESS",
            "timestamp": time.time(),
            "message": "Edge-Sentinel Cloud Readiness Pulse successful."
        })
        print("✅ Cloud sync SUCCESS! Your Master Dashboard is now cloud-ready.")
    except Exception as e:
        print(f"❌ ERROR Pulsing Cloud: {e}")

if __name__ == "__main__":
    load_dotenv()
    test_connection()
