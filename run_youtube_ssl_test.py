#!/usr/bin/env python3
"""
Quick Start: YouTube + YOLO + SSL Verification

Run this to immediately test with:
1. Download a YouTube video
2. Run YOLO inference
3. Verify detections with Gemini
4. Get a report comparing YOLO vs Gemini

No complex setup needed - just run it!
"""

import sys
import os
import subprocess

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def run_quick_test():
    """Run a quick end-to-end test"""
    print("\n" + "="*70)
    print("🚀 SmartSalai Edge-Sentinel: YouTube + SSL Verification Test")
    print("="*70 + "\n")
    
    # Check dependencies
    print("📋 Checking dependencies...")
    dependencies = {
        "yt_dlp": "pip install yt-dlp",
        "cv2": "pip install opencv-python",
        "ultralytics": "pip install ultralytics",
        "google.generativeai": "pip install google-generativeai"
    }
    
    missing = []
    for module, install_cmd in dependencies.items():
        try:
            __import__(module)
            print(f"   ✅ {module}")
        except ImportError:
            print(f"   ❌ {module} - Install with: {install_cmd}")
            missing.append(module)
    
    if missing:
        print(f"\n⚠️ Missing {len(missing)} dependencies. Install them and try again.")
        return False
    
    # Check API Keys
    print("\n📝 Checking environment...")
    from dotenv import load_dotenv
    load_dotenv()
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("OPENROUTER_API_KEY"):
        print("   ⚠️ Neither GEMINI_API_KEY nor OPENROUTER_API_KEY found")
        print("   ℹ️ Please add one of them to your .env file")
        return False
    else:
        print("   ✅ API keys configured")
        print("   ✅ GEMINI_API_KEY configured")
    
    # Run the main pipeline
    print("\n" + "="*70)
    print("🎬 Starting YouTube + YOLO + SSL Verification Pipeline")
    print("="*70 + "\n")
    
    try:
        cmd = [
            sys.executable,
            os.path.join(project_root, "scripts", "youtube_ssl_verification.py"),
            "--test-mode"
        ]
        
        result = subprocess.run(cmd, cwd=project_root)
        
        if result.returncode == 0:
            print("\n" + "="*70)
            print("✅ TEST COMPLETE!")
            print("="*70)
            print("\n📊 Results saved to: Testing videos/ssl_verification_results/")
            print("   - verification_report.json  (Main report)")
            print("   - Detailed detection data")
            print("\n📖 View results with:")
            print("   python -c \"import json; r=json.load(open('Testing videos/ssl_verification_results/verification_report.json')); print(json.dumps(r['summary'], indent=2))\"")
            return True
        else:
            print("\n❌ Pipeline failed. Check logs in logs/ssl_verify_*.log")
            return False
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = run_quick_test()
    sys.exit(0 if success else 1)
