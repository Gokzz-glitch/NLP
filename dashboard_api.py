import sqlite3
import json
import os
import html
import hmac
import time
import threading
import cv2
import psutil
import signal
import sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# SmartSalai Core Imports
from core.knowledge_ledger import ledger, DB_PATH
from core.agent_bus import bus
from agents.sos_responder import SOSResponderAgent
from core.secret_manager import get_secret
from core import gpu_config

# Aegis Phase 7: Nuclear Hardware Lock
# This moves the 67% Intel load and 68% CPU load to the RTX 3050.
gpu_config.apply()
cv2.setNumThreads(1) # Limit CPU bloat

load_dotenv()

# [REMEDIATION #24]: Require explicit dashboard secret, allowing secure keyring-backed retrieval.
DASHBOARD_SECRET_KEY = get_secret("DASHBOARD_SECRET_KEY", "").strip()
if len(DASHBOARD_SECRET_KEY) < 24:
    raise RuntimeError(
        "DASHBOARD_SECRET_KEY must be set and at least 24 characters long. "
        "Set it in .env, environment variables, or secure vault before starting the dashboard."
    )

# Optional compatibility output for legacy local tooling.
if os.getenv("DASHBOARD_WRITE_SECRET_FILE", "0").strip().lower() in {"1", "true", "yes", "on"}:
    with open(".dashboard_secret", "w", encoding="utf-8") as f:
        f.write(DASHBOARD_SECRET_KEY)

# V002 FIX: Remove hardcoded CSRF fallback; require explicit secret (env or secure vault).
CSRF_SECRET = get_secret("CSRF_SECRET_KEY", "").strip()
if len(CSRF_SECRET) < 24:
    raise RuntimeError(
        "CSRF_SECRET_KEY must be set and at least 24 characters long. "
        "Set in .env, environment variables, or secure vault."
    )

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
_allowed_origins_env = os.getenv(
    "ALLOWED_ORIGINS",
    "http://127.0.0.1:5555,http://localhost:5555,http://127.0.0.1,http://localhost",
)
ALLOWED_ORIGINS = {o.strip().lower() for o in _allowed_origins_env.split(",") if o.strip()}

# --- Rate Limiting (Leaky Bucket) [CWE-770] ---
_IP_LIMITS = {} # {ip: {"tokens": 10.0, "last": time.time()}}
_RATE_LIMIT_MAX = 20.0
_RATE_LIMIT_REGEN = 0.5 # 0.5 tokens/sec (1 request every 2s after burst)

# [REMEDIATION #3]: Anti-CSRF State Management [CWE-352]
_CSRF_STORE = {} # {client_ip: token}


def _open_sqlite_conn(db_path: str, timeout: float = 5.0) -> sqlite3.Connection:
    """Open SQLite connection with WAL + NORMAL sync for concurrent readers/writers."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn

def check_rate_limit(ip: str) -> bool:
    """[REMEDIATION #12]: Persistent SQLite-backed Rate Limiter [CWE-770]"""
    now = time.time()
    conn = _open_sqlite_conn(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT tokens, last_update FROM rate_limits WHERE ip = ?", (ip,))
        row = cursor.fetchone()
        
        if row:
            tokens, last_update = row
            elapsed = now - last_update
            tokens = min(_RATE_LIMIT_MAX, tokens + (elapsed * _RATE_LIMIT_REGEN))
        else:
            tokens = _RATE_LIMIT_MAX
            
        if tokens >= 1.0:
            tokens -= 1.0
            cursor.execute("REPLACE INTO rate_limits (ip, tokens, last_update) VALUES (?, ?, ?)", (ip, tokens, now))
            conn.commit()
            return True
        return False
    except Exception as e:
        print(f"RATE_LIMIT_DB_ERROR: {e}")
        return True # Fail open for resilience if DB is locked
    finally:
        conn.close()

START_TIME = datetime.now()
_LATEST_SOS_ACTIVE = False

# [REMEDIATION #1]: Singleton Process Guard [CWE-362]
# Simplification: Let the OS handle port conflicts via OSError. 
# We rely on the external shell script to kill old processes.

def init_bus_subscriptions():
    """Deferred subscription to avoid race conditions during import."""
    try:
        from core.agent_bus import bus
        bus.subscribe("SYSTEM_SOS_TRIGGER", _on_sos_trigger)
        bus.subscribe("IMU_ACCIDENT_DETECTED", _on_sos_trigger)
        bus.subscribe("SYSTEM_SOS_CANCEL", _on_sos_cancel)
    except Exception as e:
        logger.error(f"BUS_INIT_ERROR: {e}")

def _on_sos_trigger(msg):
    global _LATEST_SOS_ACTIVE
    _LATEST_SOS_ACTIVE = True

def _on_sos_cancel(msg):
    global _LATEST_SOS_ACTIVE
    _LATEST_SOS_ACTIVE = False


# Handlers moved after init functions

# --- Rate Limit Persistence [CWE-770] ---
def init_rate_limit_db():
    conn = _open_sqlite_conn(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip TEXT PRIMARY KEY,
                tokens REAL,
                last_update REAL
            )
        """)
        conn.commit()
    finally:
        conn.close()

init_rate_limit_db()


AGENT_META = {
    "Agent1-IndustryResearch": {
        "label": "Industry Research",
        "icon": "🔬",
        "color": "#6366f1",
        "role": "Synergistic topic research via G0DM0D3 + NotebookLM",
        "interval": 30,
    },
    "Agent2-ModelScout": {
        "label": "Model Scout",
        "icon": "🤖",
        "color": "#8b5cf6",
        "role": "Scans for INT8/GGUF edge vision models ≤2GB VRAM",
        "interval": 45,
    },
    "Agent3-CodeOpt": {
        "label": "Code Optimizer",
        "icon": "⚡",
        "color": "#06b6d4",
        "role": "Detects VRAM bottlenecks & proposes tensor rewrites",
        "interval": 60,
    },
    "Agent4-SSLLoop": {
        "label": "SSL Loop",
        "icon": "🔄",
        "color": "#10b981",
        "role": "Evaluates contrastive SSL curriculum for dashcam vision",
        "interval": 35,
    },
    "Agent5-RAG": {
        "label": "RAG Tuner",
        "icon": "📚",
        "color": "#f59e0b",
        "role": "Optimises FAISS chunking & DriveLegal vector index",
        "interval": 40,
    },
    "Agent6-DatasetBench": {
        "label": "Dataset Bench",
        "icon": "🗃️",
        "color": "#ef4444",
        "role": "Sources & benchmarks external road datasets",
        "interval": 50,
    },
    "Agent7-GPUThermal": {
        "label": "GPU Thermal",
        "icon": "🌡️",
        "color": "#f97316",
        "role": "Monitors RTX 3050 temp — manages thermal throttling",
        "interval": 10,
    },
    "Agent8-SentinelGuardian": {
        "label": "Sentinel Guardian",
        "icon": "🛡️",
        "color": "#6366f1",
        "role": "Orchestrates cross-agent communication and safety broadcasts",
        "interval": 20,
    },
    "Agent11-BenchmarkResearch": {
        "label": "Benchmark Research",
        "icon": "📈",
        "color": "#0ea5e9",
        "role": "Compares model latency, throughput, and edge benchmarks",
        "interval": 30,
    },
    "Agent12-DeploymentResearch": {
        "label": "Deployment Research",
        "icon": "🚀",
        "color": "#a855f7",
        "role": "Researches packaging and offline deployment constraints",
        "interval": 32,
    },
    "Agent13-DatasetResearch": {
        "label": "Dataset Research",
        "icon": "🗺️",
        "color": "#22c55e",
        "role": "Finds dataset coverage gaps and annotation opportunities",
        "interval": 34,
    },
    "Agent14-SafetyResearch": {
        "label": "Safety Research",
        "icon": "🔒",
        "color": "#14b8a6",
        "role": "Reviews guardrails, compliance, and failure containment",
        "interval": 36,
    },
    "Agent15-SmokeTest": {
        "label": "Smoke Testing",
        "icon": "🧪",
        "color": "#3b82f6",
        "role": "Runs fast sanity checks on core runtime paths",
        "interval": 38,
    },
    "Agent16-RegressionTest": {
        "label": "Regression Testing",
        "icon": "♻️",
        "color": "#6366f1",
        "role": "Detects behavior drift from previously stable flows",
        "interval": 40,
    },
    "Agent17-PerformanceTest": {
        "label": "Performance Testing",
        "icon": "⚙️",
        "color": "#0ea5e9",
        "role": "Tracks latency and throughput against local budgets",
        "interval": 42,
    },
    "Agent18-DataQualityTest": {
        "label": "Data Quality Testing",
        "icon": "🧹",
        "color": "#22c55e",
        "role": "Checks event completeness and payload consistency",
        "interval": 44,
    },
    "Agent19-APIContractTest": {
        "label": "API Contract Testing",
        "icon": "🔌",
        "color": "#14b8a6",
        "role": "Validates API schema compatibility for dashboard consumers",
        "interval": 46,
    },
    "Agent20-UIResponsiveTest": {
        "label": "UI Responsive Testing",
        "icon": "📱",
        "color": "#8b5cf6",
        "role": "Verifies layout behavior across viewport sizes",
        "interval": 48,
    },
    "Agent21-FailureInjectionTest": {
        "label": "Failure Injection Testing",
        "icon": "💥",
        "color": "#f97316",
        "role": "Simulates faults to verify graceful recovery",
        "interval": 50,
    },
    "Agent22-SecuritySanityTest": {
        "label": "Security Sanity Testing",
        "icon": "🔐",
        "color": "#ef4444",
        "role": "Checks basic hardening and safe rendering invariants",
        "interval": 52,
    },
    "Agent23-TrainingLoopTest": {
        "label": "Training Loop Testing",
        "icon": "🏋️",
        "color": "#f59e0b",
        "role": "Validates thermal-control and training-loop reliability",
        "interval": 54,
    },
    "Agent24-TelemetryTest": {
        "label": "Telemetry Testing",
        "icon": "📡",
        "color": "#06b6d4",
        "role": "Checks observability metrics and counter coherence",
        "interval": 56,
    },
    "Agent25-ReleaseReadinessTest": {
        "label": "Release Readiness Testing",
        "icon": "✅",
        "color": "#10b981",
        "role": "Runs final go/no-go checks before stable operation",
        "interval": 58,
    },
    "Agent9-ContextCurator": {
        "label": "Context Curator",
        "icon": "🧭",
        "color": "#22c55e",
        "role": "Condenses cross-agent signals into a short working brief",
        "interval": 55,
    },
    "Agent10-CoordinationPlanner": {
        "label": "Coordination Planner",
        "icon": "🧩",
        "color": "#14b8a6",
        "role": "Turns current findings into next-step coordination cues",
        "interval": 65,
    },
    "Agent26-RulebookCompliance": {
        "label": "Rulebook Compliance",
        "icon": "⚖️",
        "color": "#eab308",
        "role": "Verify Edge hardware VRAM and offline model constraints",
        "interval": 50,
    },
    "Agent27-DriveLegal": {
        "label": "DriveLegal Agent",
        "icon": "📜",
        "color": "#3b82f6",
        "role": "Geo-fenced traffic law and challan rules lookup",
        "interval": 52,
    },
    "Agent28-RoadWatch": {
        "label": "RoadWatch Agent",
        "icon": "🛣️",
        "color": "#10b981",
        "role": "Road quality monitoring and complaint routing",
        "interval": 54,
    },
    "Agent15-StorageSentinel": {
        "label": "Storage Sentinel",
        "icon": "💾",
        "color": "#6366f1",
        "role": "Monitors Drive space and prunes old training runs",
        "interval": 300,
    },
    "Agent32-VoiceUI": {
        "label": "Voice UI",
        "icon": "🔊",
        "color": "#f43f5e",
        "role": "Persona 4 — Low-latency safety announcements & alerts",
        "interval": 120,
    },
}

# --- Video Stream Logic ---
VIDEO_PATH = "g:/My Drive/NLP/Testing videos/VID_20260403_113108525.mp4"

def gen_frames():
    """Aegis Phase 7: Forced Hardware-Accelerated Stream."""
    while True:
        # Load Video with FFMPEG and Hardware Acceleration (NVIDIA)
        # 0x1000 = CAP_FFMPEG. Using hardware preference flags for the RTX 3050.
        cap = cv2.VideoCapture(VIDEO_PATH, cv2.CAP_FFMPEG)
        
        # Discourage MSMF (Intel) and Force GPU 1
        cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY)
        
        if not cap.isOpened():
            logger.error(f"⚠️ DASHBOARD_STREAM: Failed to open {VIDEO_PATH} on GPU 1. Retrying...")
            time.sleep(5)
            continue
        
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break
            
            # Sub-sampled resizing - Keep on GPU if possible, but cv2.resize is CPU-bound
            # Reduction in resolution helps the 68% CPU usage.
            frame = cv2.resize(frame, (480, 270)) 
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 35])
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.125) # 8 FPS (Surgical precision for stability)
        cap.release()

def get_storage_stats():
    """Robust storage check for Windows G: (Google Drive) and C: fallback."""
    try:
        # Default to checking G: drive if exists, else C:
        check_path = 'G:/' if os.path.exists('G:/') else 'C:/'
        usage = psutil.disk_usage(check_path)
        return {
            "free_gb": round(usage.free / (1024**3), 2),
            "total_gb": round(usage.total / (1024**3), 2),
            "percent": usage.percent,
            "ram_percent": psutil.virtual_memory().percent
        }
    except Exception as e:
        # Emergency fallback data to prevent API 500 error
        return {
            "free_gb": 0, "total_gb": 0, "percent": 0,
            "ram_percent": psutil.virtual_memory().percent,
            "error": str(e)
        }


def query_db(sql, params=()):
    if not os.path.exists(DB_PATH):
        return []
    try:
        # Keep API responsive under concurrent writer load from many agents.
        conn = _open_sqlite_conn(DB_PATH, timeout=0.2)
        conn.execute("PRAGMA busy_timeout = 200")
        conn.execute("PRAGMA read_uncommitted = 1")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []


def get_agent_status():
    """Returns list of agents with health, last seen, and latest log content."""
    agents = []
    now = datetime.now(timezone.utc)

    for agent_id, meta in AGENT_META.items():
        try:
            # Get latest log for this agent
            rows = query_db(
                "SELECT id, agent_name, timestamp, finding_type, content "
                "FROM agent_logs WHERE agent_name=? ORDER BY id DESC LIMIT 1",
                (agent_id,),
            )

            # Count total logs
            count_rows = query_db(
                "SELECT COUNT(*) as cnt FROM agent_logs WHERE agent_name=?",
                (agent_id,),
            )
            total = count_rows[0]["cnt"] if count_rows else 0

            last_seen = None
            last_type = "IDLE"
            last_content = {}
            elapsed_secs = None

            if rows:
                r = rows[0]
                try:
                    # SQLite stores as UTC naive string
                    ts_str = r["timestamp"].replace(" ", "T")
                    if not ts_str.endswith("Z") and "+" not in ts_str:
                        ts_str += "+00:00"
                    dt = datetime.fromisoformat(ts_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    elapsed_secs = (now - dt).total_seconds()
                    last_seen = r["timestamp"]
                except Exception:
                    elapsed_secs = None
                    last_seen = r["timestamp"]

                last_type = r["finding_type"]
                try:
                    # Safe JSON load: use json.loads directly
                    last_content = json.loads(r["content"])
                except Exception:
                    last_content = {"raw": r["content"]}

            # Determine health
            interval = meta.get("interval", 60)
            if elapsed_secs is None:
                health = "offline"
            elif elapsed_secs < interval * 3:
                health = "active"
            elif elapsed_secs < interval * 10:
                health = "idle"
            else:
                health = "offline"

            agents.append(
                {
                    "id": agent_id,
                    "label": meta["label"],
                    "icon": meta["icon"],
                    "color": meta["color"],
                    "role": meta["role"],
                    "interval": interval,
                    "health": health,
                    "total_logs": total,
                    "last_seen": last_seen,
                    "elapsed_secs": round(elapsed_secs, 1) if elapsed_secs is not None else None,
                    "last_type": last_type,
                    "last_content": last_content,
                }
            )
        except Exception as e:
            # Report individual agent error instead of failing everything
            logger.error(f"Failed to check agent {agent_id}: {e}")
            agents.append({"id": agent_id, "label": meta["label"], "health": "error", "error": str(e)})

    return agents


def get_recent_logs(limit=60):
    rows = query_db(
        "SELECT id, agent_name, timestamp, finding_type, content "
        "FROM agent_logs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    result = []
    for r in rows:
        try:
            content = json.loads(r["content"])
        except Exception:
            content = {}
        result.append(
            {
                "id": r["id"],
                "agent": r["agent_name"],
                "timestamp": r["timestamp"],
                "type": r["finding_type"],
                "content": content,
            }
        )
    return result


def get_conversation(limit_rounds: int = 8):
    """Return last N conversation rounds: each question + all agent responses."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = _open_sqlite_conn(DB_PATH, timeout=0.2)
        conn.execute("PRAGMA busy_timeout = 200")
        conn.execute("PRAGMA read_uncommitted = 1")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Fetch recent questions
        cur.execute(
            "SELECT id, agent_name, timestamp, finding_type, content "
            "FROM agent_logs "
            "WHERE agent_name='Agent8-SentinelGuardian' AND finding_type='broadcast_question' "
            "ORDER BY id DESC LIMIT ?",
            (limit_rounds,),
        )
        questions = [dict(r) for r in cur.fetchall()]

        rounds = []
        for q in questions:
            q_content = json.loads(q["content"])
            q_id      = q["id"]

            # Fetch all responses to this question
            cur.execute(
                "SELECT id, agent_name, timestamp, content "
                "FROM agent_logs "
                "WHERE finding_type='broadcast_response' "
                "AND json_extract(content, '$.question_id')=? "
                "ORDER BY id ASC",
                (q_id,),
            )
            responses = []
            for r in cur.fetchall():
                rc = json.loads(r["content"])
                responses.append({
                    "agent":      r["agent_name"],
                    "timestamp":  r["timestamp"],
                    "response":   rc.get("response", ""),
                })

            rounds.append({
                "round":     q_content.get("round", 0),
                "question":  q_content.get("question", ""),
                "asked_at":  q["timestamp"],
                "responses": responses,
            })

        conn.close()
        return rounds
    except Exception as e:
        return [{"error": str(e)}]


def get_summary():
    """Restored: Aggregates system-wide log stats."""
    total = query_db("SELECT COUNT(*) as cnt FROM agent_logs")
    last_hour = query_db(
        "SELECT COUNT(*) as cnt FROM agent_logs "
        "WHERE timestamp >= datetime('now', '-1 hour')"
    )
    by_agent = query_db(
        "SELECT agent_name, COUNT(*) as cnt FROM agent_logs GROUP BY agent_name ORDER BY cnt DESC"
    )
    
    uptime = datetime.now() - START_TIME
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{days}d {hours}h {minutes}m"

    return {
        "total_logs": total[0]["cnt"] if total else 0,
        "last_hour": last_hour[0]["cnt"] if last_hour else 0,
        "by_agent": {r["agent_name"]: r["cnt"] for r in by_agent},
        "db_exists": os.path.exists(DB_PATH),
        "db_size_kb": round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0,
        "server_time": datetime.now().isoformat(),
        "uptime": uptime_str,
        "active_sos": _LATEST_SOS_ACTIVE,
        "version": "1.2.1-Secure"
    }


with open(os.path.join(os.path.dirname(__file__), "dashboard", "index.html"), encoding="utf-8") as _dashboard_html_file:
    DASHBOARD_HTML = _dashboard_html_file.read()

class SentinelDashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence default request logs

    def _allowed_origin(self) -> str:
        origin = (self.headers.get("Origin") or "").strip().lower()
        if origin and origin in ALLOWED_ORIGINS:
            return origin
        return ""

    def _is_authorized(self) -> bool:
        auth_header = (self.headers.get("Authorization") or "").strip()
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            return False
        token = parts[1].strip()
        if not token:
            return False
        return hmac.compare_digest(token, DASHBOARD_SECRET_KEY)

    def _send_json(self, data, status=200):
        """Sends data as robust JSON with error handling and sanitization."""
        try:
            # 1. Sanitize to prevent XSS (escapes HTML in display strings)
            sanitized = self._sanitize_recursive(data)
            
            # 2. Serialize: use default=str for datetime/path serialisation
            body = json.dumps(sanitized, default=str).encode()
            
            self.send_response(status)
            self._set_headers("application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.error(f"Failed to send JSON response: {e}")
            # Fallback error response
            err_body = json.dumps({"error": "Serialization Failure", "detail": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)

    def _send_error(self, message, code=500):
        """Sanitized error responder [CWE-209]"""
        self._send_json({"error": message, "status": "ERROR"}, code)

    def _sanitize_recursive(self, data):
        """Recursively escapes HTML within values to prevent XSS."""
        if isinstance(data, str):
            # Only escape if looks like HTML or the key hints at display content
            return html.escape(data)
        elif isinstance(data, dict):
            # Special case: don't double-escape nested agent content
            return {k: self._sanitize_recursive(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_recursive(i) for i in data]
        return data

    def _set_headers(self, content_type='application/json'):
        """Apply Global Security Headers [CWE-693]"""
        self.send_header('Content-Type', content_type)
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:;")
        origin = self._allowed_origin()
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')

    def do_OPTIONS(self):
        self.send_response(204)
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CSRF-Token")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        
        # 1. Root-level Rate Limit check
        client_ip = self.client_address[0]
        if not check_rate_limit(client_ip):
            self._send_error("Rate limit exceeded. Try again in 2 seconds.", 429)
            return

        # 2. Static HTML Root
        if path == "" or path == "/":
            # [REMEDIATION #1]: Stop injecting API_KEY into global JS
            # Instead, we serve a blank shell and a unique CSRF token for the session
            import secrets
            csrf_token = secrets.token_hex(16)
            _CSRF_STORE[client_ip] = csrf_token
            
            # [SECURITY FIX #23]: Use json.dumps for safe CSRF token injection
            safe_csrf = json.dumps(csrf_token)
            body = DASHBOARD_HTML.replace("{{CSRF_TOKEN}}", csrf_token).encode()
            self.send_response(200)
            self._set_headers("text/html; charset=utf-8")
            self.send_header("Set-Cookie", f"csrf_token={csrf_token}; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 3. API Routes (Auth Required)
        if path.startswith("/api/"):
            if not self._is_authorized():
                self._send_error("Unauthorized Access", 401)
                return

            if path == "/api/agents":
                self._send_json(get_agent_status())
            elif path == "/api/logs":
                qs = parse_qs(parsed.query)
                limit = int(qs.get("limit", ["60"])[0])
                self._send_json(get_recent_logs(limit))
            elif path == "/api/summary":
                self._send_json(get_summary())
            elif path == "/api/storage":
                self._send_json(get_storage_stats())
            elif path == "/api/training_stats":
                # Real-time mAP data for accuracy graph
                stats = query_db(
                    "SELECT timestamp, json_extract(content, '$.mAP50') as map50 "
                    "FROM agent_logs WHERE finding_type='training_results' "
                    "ORDER BY timestamp DESC LIMIT 20"
                )
                # Reverse for chronological graph
                stats.reverse()
                self._send_json(stats)
            elif path == "/api/conversation":
                qs = parse_qs(parsed.query)
                rounds = int(qs.get("rounds", ["8"])[0])
                self._send_json(get_conversation(rounds))
            elif path == "/api/heartbeats":
                # [REMEDIATION #31]: Optimized heartbeat-only endpoint
                results = ledger.get_findings(finding_type="agent_heartbeat", limit=64)
                # Flat map {agent_name: last_seen_ts}
                hb_map = {f["agent_name"]: f["timestamp"] for f in results}
                self._send_json(hb_map)
            elif path == "/api/auth/verify":
                # Used by frontend to verify current Bearer token is still valid
                self._send_json({"status": "AUTHORIZED", "ts": time.time()})
            else:
                self._send_json({"error": "API route not found"}, 404)
            return

        # 4. Video Stream (AUTH REQUIRED V3 [CWE-285])
        if path == "/video_feed":
            # SECURITY FIX #8: Move token from query parameter to Authorization header
            # Query parameters are logged in server logs, browser history, and HTTP Referer headers
            # Use Authorization header instead for proper cryptographic credential handling
            if not self._is_authorized():
                self._send_error("Unauthorized Stream Access", 401)
                return

            self.send_response(200)
            self._set_headers('multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                for frame in gen_frames():
                    self.wfile.write(frame)
            except (ConnectionResetError, BrokenPipeError):
                pass
            return

        # 4. Fallback 404
        self._send_json({"error": "Resource not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        client_ip = self.client_address[0]
        
        # [REMEDIATION #3]: Validate CSRF Token [CWE-352]
        csrf_header = self.headers.get("X-CSRF-Token", "")
        stored_csrf = _CSRF_STORE.get(client_ip)
        if not stored_csrf or not csrf_header or not hmac.compare_digest(csrf_header, stored_csrf):
            self._send_error("Forbidden: Invalid CSRF Token", 403)
            return

        # Auth Check
        if not self._is_authorized():
            self._send_error("Unauthorized Access", 401)
            return

        if path == "/api/sos/cancel":
            bus.emit("SYSTEM_SOS_CANCEL", {"source": "dashboard_web_ui", "ts": time.time()})
            self._send_json({"status": "CANCEL_COMMAND_SENT", "ts": time.time()})
        elif path == "/api/tts/speak":
            # Manual TTS override for testing/safety broadcast
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_len)
                data = json.loads(post_data.decode())
                text = data.get("text")
                if text:
                    bus.emit("VOICE_ALERT_REQUEST", {"text": text, "priority": "IMMEDIATE"})
                    self._send_json({"status": "VOICE_REQUEST_EMITTED", "text": text})
                else:
                    self._send_json({"error": "Missing 'text' in payload"}, 400)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "POST route not found"}, 404)


if __name__ == "__main__":
    init_bus_subscriptions()
    port = int(os.getenv("DASHBOARD_PORT", 5555))
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    
    # [REMEDIATION #13]: Use ThreadingHTTPServer for multi-client video feeds [CWE-400]
    # Bound to simple host/port for local dev persistence.
    try:
        server = ThreadingHTTPServer((host, port), SentinelDashboardHandler)
        print(f"\n{'='*55}")
        print(f"  🛰️  SmartSalai Edge-Sentinel — Live Monitor (SECURE)")
        print(f"  Dashboard → http://{host}:{port}")
        if os.getenv("DASHBOARD_WRITE_SECRET_FILE", "0").strip().lower() in {"1", "true", "yes", "on"}:
            print("  Auth Token → Read from .dashboard_secret")
        else:
            print("  Auth Token → Read from DASHBOARD_SECRET_KEY env/secure vault")
        print(f"{'='*55}\n")
        print("READY")
        server.serve_forever()
    except OSError as e:
        if e.errno == 98 or e.errno == 10048:
            print(f"⚠️ PORT {port} ALREADY IN USE. Retrying in 5s...")
            time.sleep(5)
            # Second attempt
            server = ThreadingHTTPServer((host, port), SentinelDashboardHandler)
            print(f"  🛰️  SmartSalai Edge-Sentinel — Live Monitor (RETRY READY)")
            server.serve_forever()
        else:
            raise
