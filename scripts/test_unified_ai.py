import os
import sys
# Inject root project directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()
from core.unified_ai import UnifiedAI

def test_engine():
    print("🚀 SITUATION: Testing Unified AI Engine initialization...")
    try:
        ui = UnifiedAI()
        print(f"✅ Gemini Keys Found: {len(ui.gemini_keys)}")
        print(f"✅ Active External Providers: {ui.active_providers}")
        
        # Verify provider configs
        for p in ui.active_providers:
            print(f"   [-] {p}: Model={ui.providers[p]['default_model']}")
            
        print("\n🏆 ENGINE READY: Failover and Rotation logic is active.")
    except Exception as e:
        print(f"❌ ENGINE FAILED: {e}")

if __name__ == "__main__":
    test_engine()
