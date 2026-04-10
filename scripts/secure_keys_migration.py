import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from core.secret_manager import set_secret
from dotenv import load_dotenv

load_dotenv()

SECRETS_TO_MIGRATE = [
    "DASHBOARD_SECRET_KEY",
    "FERNET_KEY",
    "GEMINI_API_KEY",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_CLIENT_EMAIL"
]

def migrate():
    print("🚀 SmartSalai Edge-Sentinel — Secure Key Migration")
    print("-----------------------------------------------")
    
    migrated_count = 0
    for key in SECRETS_TO_MIGRATE:
        val = os.getenv(key)
        if val:
            print(f"Moving {key} to OS Secure Vault...")
            try:
                set_secret(key, val)
                migrated_count += 1
            except Exception as e:
                print(f"❌ Failed to migrate {key}: {e}")
        else:
            print(f"⚠️ {key} not found in .env, skipping.")
            
    print("-----------------------------------------------")
    print(f"✅ Migration Complete! {migrated_count} keys stored in OS Keyring.")
    print("IMPORTANT: You can now remove these values from your .env file.")

if __name__ == "__main__":
    migrate()
