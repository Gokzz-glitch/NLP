import sqlite3
import json
import os
import hmac
import hashlib
import re
import logging
import queue
import threading
import time
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
# SECURITY FIX #4: Require dedicated ledger HMAC key, avoid auth-secret reuse
_ENCRYPTION_KEY_STR = os.getenv("LEDGER_HMAC_KEY")
if not _ENCRYPTION_KEY_STR:
    allow_legacy = os.getenv("LEDGER_ALLOW_DASHBOARD_KEY", "0").strip().lower() in {"1", "true", "yes", "on"}
    if allow_legacy:
        _ENCRYPTION_KEY_STR = os.getenv("DASHBOARD_SECRET_KEY", "")
    if not _ENCRYPTION_KEY_STR:
        raise EnvironmentError(
            "LEDGER_HMAC_KEY not set in environment. "
            "Set LEDGER_HMAC_KEY before running knowledge ledger "
            "(legacy fallback requires LEDGER_ALLOW_DASHBOARD_KEY=1)."
        )
_ENCRYPTION_KEY = _ENCRYPTION_KEY_STR.encode()

# Move DB path to local non-synced directory to avoid massive GoogleDriveFS CPU overhead
_LOCAL_HOME = os.path.expanduser("~")
_DB_DIR = os.path.join(_LOCAL_HOME, "SmartSalai_Local")
if not os.path.exists(_DB_DIR):
    os.makedirs(_DB_DIR, exist_ok=True)
DB_PATH = os.path.join(_DB_DIR, "knowledge_ledger.db")

class KnowledgeLedger:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
        
        # [REMEDIATION #33]: Async Write Queue [CWE-662]
        # Multi-agent bursts will no longer block on "Database is locked"
        # SECURITY FIX #13: Add maxsize=5000 to prevent unbounded queue growth
        # If queue fills up, producers will block (backpressure) instead of consuming infinite memory
        self._write_queue = queue.Queue(maxsize=5000)
        self._dlq_dir = Path("logs/dlq")
        self._dlq_dir.mkdir(parents=True, exist_ok=True)
        
        # Start Worker Thread
        self._worker = threading.Thread(target=self._database_worker, daemon=True)
        self._worker.start()

    def _open_db(self) -> sqlite3.Connection:
        """Open SQLite connection with concurrency-safe WAL settings."""
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA journal_mode = WAL;')
        conn.execute('PRAGMA synchronous = NORMAL;')
        busy_timeout_ms = int(os.getenv("LEDGER_BUSY_TIMEOUT_MS", "15000"))
        conn.execute(f'PRAGMA busy_timeout = {busy_timeout_ms};')
        return conn

    def _database_worker(self):
        """Background consumer for telemetry findings"""
        while True:
            # Blocks until item arrives
            agent_name, finding_type, content_json, signature = self._write_queue.get()
            try:
                write_retries = int(os.getenv("LEDGER_WRITE_RETRIES", "4"))
                base_sleep = float(os.getenv("LEDGER_WRITE_RETRY_SLEEP_SEC", "0.03"))
                wrote = False
                last_error = None

                for attempt in range(write_retries + 1):
                    try:
                        conn = self._open_db()
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO agent_logs (agent_name, finding_type, content, signature)
                            VALUES (?, ?, ?, ?)
                        ''', (agent_name, finding_type, content_json, signature))
                        conn.commit()
                        conn.close()
                        wrote = True
                        break
                    except sqlite3.OperationalError as e:
                        last_error = e
                        msg = str(e).lower()
                        if "database is locked" in msg and attempt < write_retries:
                            time.sleep(base_sleep * (attempt + 1))
                            continue
                        raise

                if not wrote and last_error is not None:
                    raise last_error
            except Exception as e:
                # [REMEDIATION #30]: Dead Letter Queue Fallsback [DR-03]
                self._handle_dlq(agent_name, finding_type, content_json, e)
            finally:
                self._write_queue.task_done()

    def _handle_dlq(self, agent, type, content, error):
        """Saves telemetry to local JSON if DB fails"""
        logger.error(f"DLQ_TRIGGERED: DB Fail ({error}). Saving finding to fallback storage.")
        fallback_file = self._dlq_dir / f"telemetry_fail_{time.time()}.json"
        try:
            with open(fallback_file, "w") as fh:
                json.dump({"agent": agent, "type": type, "content": content, "err": str(error)}, fh)
        except:
            pass # Total I/O failure

    def _init_db(self):
        conn = self._open_db()
        cursor = conn.cursor()
        
        # Optimize for high-concurrency edge performance
        cursor.execute('PRAGMA journal_mode = WAL;')
        cursor.execute('PRAGMA synchronous = NORMAL;')
        cursor.execute('PRAGMA auto_vacuum = INCREMENTAL;')
        
        # Main generic log table across all agents
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                finding_type TEXT,
                content JSON NOT NULL,
                signature TEXT
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_agent_name ON agent_logs(agent_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_finding_type ON agent_logs(finding_type)')
        
        # [REMEDIATION #12]: Persistent Rate Limits [CWE-770]
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip TEXT PRIMARY KEY,
                tokens REAL,
                last_update REAL
            )
        ''')
        
        # [REMEDIATION #20]: Automated SQL Migration Guard [CWE-20]
        # Probes the existing schema to ensure column integrity after upgrades
        try:
            cursor.execute("PRAGMA table_info(agent_logs)")
            columns = [col[1] for col in cursor.fetchall()]
            if columns and "signature" not in columns:
                print("REMEDIATION: Legacy agent_logs detected. Adding 'signature' column...")
                cursor.execute("ALTER TABLE agent_logs ADD COLUMN signature TEXT")
        except Exception as e:
            logger.error(f"MIGRATION_ERROR: {e}")

        conn.commit()
        conn.close()

    def _mask_sensitive(self, data: Any) -> Any:
        """
        Recursively masks PII and secrets (GPS, Phone, Keys) [CWE-312]
        """
        if isinstance(data, str):
            # Mask typical API Key patterns (32+ hex/alphanumeric)
            if len(data) > 30 and re.match(r'^[a-zA-Z0-9_\-]+$', data):
                return data[:4] + "*" * (len(data)-8) + data[-4:]
            # Mask potential phone numbers (simple 10-digit)
            if re.match(r'^\d{10}$', data):
                return data[:3] + "****" + data[-3:]
            return data
        elif isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                # Explicitly mask GPS coordinates for privacy
                if k.lower() in ("lat", "lon", "latitude", "longitude"):
                    new_dict[k] = "[REDACTED_PII]"
                else:
                    new_dict[k] = self._mask_sensitive(v)
            return new_dict
        elif isinstance(data, list):
            return [self._mask_sensitive(i) for i in data]
        return data

    def log_finding(self, agent_name, finding_type, content):
        """Generic structured finding logger - NOW ASYNC/QUEUE-BACKED."""
        # [SECURITY FIX #78]: Mask PII before JSON serialization
        masked_content = self._mask_sensitive(content)
        content_json = json.dumps(masked_content)
        
        # [SECURITY FIX #77]: HMAC Integrity Check
        signature = hmac.new(_ENCRYPTION_KEY, content_json.encode(), hashlib.sha256).hexdigest()
        
        # [REMEDIATION #33]: Push to queue for background write
        queue_put_timeout = float(os.getenv("LEDGER_QUEUE_PUT_TIMEOUT_SEC", "0.2"))
        try:
            self._write_queue.put((agent_name, finding_type, content_json, signature), timeout=queue_put_timeout)
        except queue.Full:
            self._handle_dlq(agent_name, finding_type, content_json, "queue_full")
        
        
    def get_findings(self, agent_name: str = None, finding_type: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._open_db()
        cursor = conn.cursor()
        
        query = 'SELECT id, agent_name, timestamp, finding_type, content FROM agent_logs WHERE 1=1'
        params = []
        
        if agent_name:
            query += ' AND agent_name = ?'
            params.append(agent_name)
        if finding_type:
            query += ' AND finding_type = ?'
            params.append(finding_type)
            
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        
        findings = []
        for r in rows:
            findings.append({
                "id": r[0],
                "agent_name": r[1],
                "timestamp": r[2],
                "finding_type": r[3],
                "content": json.loads(r[4])
            })
            
        return findings

    def delete_findings(self, agent_name: str = None, finding_type: str = None, older_than_mins: int = None):
        """
        Maintenance: delete redundant noise to keep DB slim [CWE-400]
        """
        conn = self._open_db()
        cursor = conn.cursor()
        
        query = "DELETE FROM agent_logs WHERE 1=1"
        params = []
        
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if finding_type:
            query += " AND finding_type = ?"
            params.append(finding_type)
        if older_than_mins:
            # SQLite datetime arithmetic: 'now', '-60 minutes'
            query += " AND timestamp < datetime('now', ?)"
            params.append(f"-{older_than_mins} minutes")
            
        try:
            cursor.execute(query, tuple(params))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"LEDGER_MAINTENANCE: Pruned {cursor.rowcount} records (type={finding_type or 'any'})")
        except Exception as e:
            logger.error(f"LEDGER_MAINTENANCE_ERROR: {e}")
        finally:
            conn.close()

    def close(self):
        """Commits and closes the connection cleanly."""
        try:
            conn = self._open_db()
            conn.commit()
            conn.close()
            # If auto_vacuum is set, this is a good place to also run a small incremental vacuum.
            conn = self._open_db()
            conn.execute("PRAGMA incremental_vacuum(50)")
            conn.close()
        except:
            pass

# Singleton instance
ledger = KnowledgeLedger()

if __name__ == "__main__":
    print(f"Ledger initialized at {DB_PATH}")
    ledger.log_finding("System", "Init", {"status": "ok", "message": "Ledger created successfully."})
    print(ledger.get_findings("System"))
