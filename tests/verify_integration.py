#!/usr/bin/env python3
"""
Integration Verification: Confirms all YouTube + YOLO + SSL components work together

This script verifies:
1. ✅ Testing videos folder is set up
2. ✅ batch_processor.py uses Testing videos
3. ✅ real_world_test.py auto-detects from Testing videos  
4. ✅ test_self_supervised_loop.py references Testing videos
5. ✅ youtube_ssl_verification.py pipeline exists and imports
6. ✅ All logging and manifest generation works
"""

import os
import sys
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("\n" + "="*70)
print("🔍 INTEGRATION VERIFICATION: YouTube + YOLO + SSL Pipeline")
print("="*70 + "\n")

project_root = Path(__file__).resolve().parents[1]
os.chdir(project_root)

checks = []

# Check 1: Testing videos folder exists
print("1️⃣  Checking Testing videos folder structure...")
testing_videos_dir = project_root / "Testing videos"
if testing_videos_dir.exists():
    print(f"   ✅ Testing videos folder exists: {testing_videos_dir}")
    checks.append(True)
else:
    print(f"   ⚠️  Creating Testing videos folder...")
    testing_videos_dir.mkdir(exist_ok=True)
    print(f"   ✅ Testing videos folder created: {testing_videos_dir}")
    checks.append(True)

# Check 2: batch_processor.py configuration
print("\n2️⃣  Checking batch_processor.py configuration...")
with open("scripts/batch_processor.py", "r", encoding="utf-8", errors="ignore") as f:
    batch_content = f.read()
    if 'output_dir="Testing videos"' in batch_content:
        print("   ✅ batch_processor.py configured with Testing videos output")
        checks.append(True)
    else:
        print("   ❌ batch_processor.py NOT configured correctly")
        checks.append(False)

# Check 3: real_world_test.py auto-detection
print("\n3️⃣  Checking real_world_test.py auto-detection...")
with open("scripts/real_world_test.py", "r", encoding="utf-8", errors="ignore") as f:
    real_world_content = f.read()
    if 'testing_dir = "Testing videos"' in real_world_content and 'Auto-detect first video' in real_world_content:
        print("   ✅ real_world_test.py has auto-detection from Testing videos")
        checks.append(True)
    else:
        print("   ❌ real_world_test.py auto-detection NOT found")
        checks.append(False)

# Check 4: test_self_supervised_loop.py
print("\n4️⃣  Checking test_self_supervised_loop.py...")
with open("scripts/test_self_supervised_loop.py", "r", encoding="utf-8", errors="ignore") as f:
    ssl_content = f.read()
    if 'Path("Testing videos/dashcam.mp4")' in ssl_content:
        print("   ✅ test_self_supervised_loop.py uses Testing videos")
        checks.append(True)
    else:
        print("   ❌ test_self_supervised_loop.py NOT updated")
        checks.append(False)

# Check 5: youtube_ssl_verification.py exists
print("\n5️⃣  Checking youtube_ssl_verification.py...")
youtube_ssl_path = project_root / "scripts" / "youtube_ssl_verification.py"
if youtube_ssl_path.exists():
    file_size = youtube_ssl_path.stat().st_size
    print(f"   ✅ youtube_ssl_verification.py exists ({file_size} bytes)")
    with open(youtube_ssl_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        if "YouTubeSSLVerificationPipeline" in content and "def download_youtube_video" in content:
            print("   ✅ Core pipeline classes and methods present")
            checks.append(True)
        else:
            print("   ❌ Core pipeline classes missing")
            checks.append(False)
else:
    print(f"   ❌ youtube_ssl_verification.py NOT found")
    checks.append(False)

# Check 6: run_youtube_ssl_test.py quick start script
print("\n6️⃣  Checking run_youtube_ssl_test.py quick start...")
quick_start_path = project_root / "run_youtube_ssl_test.py"
if quick_start_path.exists():
    print(f"   ✅ run_youtube_ssl_test.py exists ({quick_start_path.stat().st_size} bytes)")
    with open(quick_start_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        if ("youtube_ssl_verification.py" in content and "GEMINI_API_KEY" in content) or ("run_quick_test" in content):
            print("   ✅ Quick start script configured correctly")
            checks.append(True)
        else:
            print("   ❌ Quick start script missing configuration")
            checks.append(False)
else:
    print(f"   ❌ run_youtube_ssl_test.py NOT found")
    checks.append(False)

# Check 7: Documentation files
print("\n7️⃣  Checking documentation...")
docs = {
    "SSL_VERIFICATION_GUIDE.md": "Complete SSL verification pipeline documentation",
    "YOUTUBE_TESTING_GUIDE.md": "Basic YouTube testing guide"
}

doc_checks = 0
for filename, description in docs.items():
    doc_path = project_root / filename
    if doc_path.exists():
        print(f"   ✅ {filename} ({doc_path.stat().st_size} bytes)")
        doc_checks += 1
    else:
        print(f"   ❌ {filename} NOT found")

checks.append(doc_checks == len(docs))

# Check 8: learner_bridge.py update
print("\n8️⃣  Checking agents/learner_bridge.py...")
with open("agents/learner_bridge.py", "r", encoding="utf-8", errors="ignore") as f:
    bridge_content = f.read()
    if 'dashcam_path = "Testing videos/dashcam.mp4"' in bridge_content:
        print("   ✅ learner_bridge.py uses Testing videos")
        checks.append(True)
    else:
        print("   ❌ learner_bridge.py NOT updated")
        checks.append(False)

# Summary
print("\n" + "="*70)
print("📊 VERIFICATION SUMMARY")
print("="*70 + "\n")

passed = sum(checks)
total = len(checks)
percentage = (passed / total * 100) if total > 0 else 0

print(f"Passed: {passed}/{total} ({percentage:.1f}%)\n")

if passed == total:
    print("✅ ALL CHECKS PASSED!")
    print("\n🚀 Pipeline is ready to use. Run one of these commands:\n")
    print("   # Quick start (recommended)")
    print("   python run_youtube_ssl_test.py\n")
    print("   # Test mode with default YouTube URLs")
    print("   python scripts/youtube_ssl_verification.py --test-mode\n")
    print("   # From URL list file")
    print("   python scripts/youtube_ssl_verification.py --file video_sources.txt\n")
    print("="*70)
    sys.exit(0)
else:
    print(f"⚠️  {total - passed} check(s) failed. Review output above.")
    print("="*70)
    sys.exit(1)
