import time
import os
import json
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from core.secret_manager import get_secret

load_dotenv()
# SECURITY FIX #3: No hardcoded default fallback; require environment variable
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY")
if not DASHBOARD_SECRET_KEY:
    raise EnvironmentError(
        "DASHBOARD_SECRET_KEY not set in environment. "
        "Please set this variable before running Firebase client. "
        "Use: export DASHBOARD_SECRET_KEY='<your-secret-key>'"
    )

logger = logging.getLogger("edge_sentinel.firebase_client")

class FirebaseClient:
    """
    Standardized client for SmartSalai Firebase/Firestore operations.
    Handles initialization and high-level CRUD for road hazards.
    Includes Vuln #23 fix: Token Bucket Rate Limiting for Cloud Cost Safety.
    """
    _instance = None
    _db = None
    
    # Rate Limiting State (Leaky Bucket)
    _tokens = 10.0
    _max_tokens = 10.0
    _sustained_rate = 0.2  # 1 token every 5 seconds (0.2 tokens/sec)
    _last_checked = time.time()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Loads and decrypts Firebase credentials from encrypted .enc file."""
        # Fetch shared encryption key from Secure OS Vault (Vuln #2 Fix)
        self.fernet_key = get_secret("FERNET_KEY")
        if not self.fernet_key:
            logger.warning("FERNET_KEY not found in Secure Vault. Cloud sync may fail.")
        
        project_id = get_secret("FIREBASE_PROJECT_ID")
        cred_path = get_secret("FIREBASE_PRIVATE_KEY_PATH", "config/firebase_credentials.enc")

        if not project_id:
            logger.warning("FIREBASE_PROJECT_ID not set. Cloud sync disabled.")
            return

        try:
            if cred_path and os.path.exists(cred_path):
                if cred_path.endswith(".enc") and self.fernet_key:
                    # In-memory decryption
                    f = Fernet(self.fernet_key.encode('utf-8'))
                    with open(cred_path, "rb") as enc_file:
                        decrypted_data = f.decrypt(enc_file.read())
                    cred_dict = json.loads(decrypted_data.decode("utf-8"))
                    cred = credentials.Certificate(cred_dict)
                else:
                    # Fallback plaintext JSON parsing for edge cases
                    cred = credentials.Certificate(cred_path)

                firebase_admin.initialize_app(cred, {
                    'projectId': project_id,
                })
            else:
                # Fallback to default credentials (e.g. for Colab or service account env)
                firebase_admin.initialize_app(options={'projectId': project_id})
            
            self._db = firestore.client()
            logger.info(f"Firebase initialized for project: {project_id}")
        except Exception as e:
            logger.error(f"Firebase initialization failed: {e}")
            self._db = None

    def is_connected(self) -> bool:
        return self._db is not None

    def _consume_token(self) -> bool:
        """Check rate limits and consume a token if available."""
        now = time.time()
        # Regenerate tokens since last check
        elapsed = now - self._last_checked
        self._tokens = min(self._max_tokens, self._tokens + (elapsed * self._sustained_rate))
        self._last_checked = now
        
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def upsert_pothole(self, pothole_id: str, data: Dict[str, Any]) -> bool:
        """Upload or update a verified pothole coordinate."""
        if not self.is_connected(): return False
        if not self._consume_token():
            logger.warning(f"Firebase Rate Limit Exceeded. Skipping {pothole_id}")
            return False
        try:
            doc_ref = self._db.collection('potholes').document(pothole_id)
            doc_ref.set(data, merge=True)
            logger.debug(f"Pothole {pothole_id} synced to Firebase.")
            return True
        except Exception as e:
            logger.error(f"Firebase Pothole Sync Error: {e}")
            return False

    def log_violation(self, violation_id: str, data: Dict[str, Any]) -> bool:
        """Store MVA violation record for cross-device lookup."""
        if not self.is_connected(): return False
        if not self._consume_token():
            logger.warning(f"Firebase Rate Limit Exceeded. Skipping {violation_id}")
            return False
        try:
            doc_ref = self._db.collection('violations').document(violation_id)
            doc_ref.set(data)
            logger.debug(f"Violation {violation_id} synced to Firebase.")
            return True
        except Exception as e:
            logger.error(f"Firebase Violation Sync Error: {e}")
            return False

    def push_telemetry(self, node_id: str, data: Dict[str, Any]):
        """Push real-time system health (GPU/RAM) to cloud dashboard."""
        if not self.is_connected(): return
        # Telemetry uses a sub-token check or just counts against the main pool
        if not self._consume_token():
            return
        try:
            doc_ref = self._db.collection('telemetry').document(node_id)
            doc_ref.set(data, merge=True)
        except Exception as e:
            logger.error(f"Firebase Telemetry Sync Error: {e}")

# Global instance
fb_client = FirebaseClient()
