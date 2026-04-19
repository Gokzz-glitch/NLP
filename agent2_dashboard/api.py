"""
Agent 2 - ModelScout Live Dashboard API (INDUSTRY HARDENED v1.4.0)
Fleet Hub with Tactical Resilience & Retrospective Sync.
"""
import sqlite3
import json
import os
import asyncio
import time
import math
import secrets
import hashlib
import urllib.request
import logging
import hmac
from datetime import timedelta
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from typing import Set, Dict, List, Optional
from pydantic import BaseModel

# SmartSalai Core
from core.knowledge_ledger import DB_PATH
from core.agent_bus import bus
from core.secret_manager import get_secret
from core.tls_config import https_redirect_middleware
from core.payment_gateway import (
    PaymentGatewayError,
    SignatureVerificationError,
    create_fleet_pass_order,
    verify_razorpay_signature,
)

app = FastAPI(title="Sentinel Absolute Hub v1.4.0")

# V020 FIX: Enforce HTTPS redirect
app = https_redirect_middleware(app)

PREDICTIVE_DB_PATH = os.getenv("EDGE_SPATIAL_DB_PATH", "edge_spatial.db")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "AGENT2_ALLOWED_ORIGINS",
            os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8765,http://localhost:8765"),
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# SECURITY FIX #5: No hardcoded default fallback; require environment variable
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY")
if not DASHBOARD_SECRET_KEY:
    raise EnvironmentError(
        "DASHBOARD_SECRET_KEY not set in environment. "
        "Please set this variable before running Flask dashboard. "
        "Use: export DASHBOARD_SECRET_KEY='<your-secret-key>'"
    )

FLEET_HALT_TOKEN = os.getenv("FLEET_HALT_TOKEN") or DASHBOARD_SECRET_KEY
if not os.getenv("FLEET_HALT_TOKEN"):
    logging.getLogger("FleetHalt").warning(
        "FLEET_HALT_TOKEN not set; falling back to DASHBOARD_SECRET_KEY."
    )

# 🛠️ OMEGA UTILS: Haversine for Spatial Deduplication
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 # Meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- Absolute Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.authed_connections: Set[WebSocket] = set()
        self.fleet_health: Dict[WebSocket, dict] = {}
        # 🛡️ SECURITY: {IP: Count}
        self.ip_counts: Dict[str, int] = {}
        self.failed_auth_counts: Dict[str, int] = {}
        self.blacklisted_ips: Set[str] = set()
        # 🕵️ FLEET: Deduplication & Tenants
        self.recent_hazards: List[Dict] = []
        self.fleet_tenants: Dict[WebSocket, str] = {} # WebSocket -> FleetID
        self.telemetry_health_cache: Dict = {
            "status": "WARMING_UP",
            "reason": "Telemetry source not polled yet.",
            "ts_ms": int(time.time() * 1000),
        }
        # F001 FIX: Thread lock to prevent race conditions
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        async with self._lock:
            client_ip = websocket.client.host
            # 🛡️ BLACKLIST CHECK (TC9)
            if client_ip in self.blacklisted_ips:
                await websocket.close(code=4003)
                return False
                
            if self.ip_counts.get(client_ip, 0) >= 3:
                await websocket.close(code=4003)
                return False
            
            await websocket.accept()
            self.active_connections.add(websocket)
            self.ip_counts[client_ip] = self.ip_counts.get(client_ip, 0) + 1
            return True

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                client_ip = websocket.client.host
                self.ip_counts[client_ip] = max(0, self.ip_counts.get(client_ip, 1) - 1)
                
            self.active_connections.discard(websocket)
            self.authed_connections.discard(websocket)
            self.fleet_health.pop(websocket, None)
            self.fleet_tenants.pop(websocket, None)

    async def broadcast(self, message: dict, fleet_id: str = "GLOBAL"):
        async with self._lock:
            if not self.authed_connections:
                return
            data = json.dumps(message)
            # 🐝 TC48: Multi-Tenant Segregation
            tasks = []
            for conn in list(self.authed_connections):
                if self.fleet_tenants.get(conn) == fleet_id or fleet_id == "GLOBAL":
                    tasks.append(self._safe_send(conn, data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, websocket: WebSocket, data: str):
        try:
            await websocket.send_text(data)
        except Exception:
            await self.disconnect(websocket)

    async def heartbeat(self):
        # D016 FIX: Track last heartbeat per connection and timeout inactive ones
        last_heartbeat: Dict[WebSocket, float] = {}
        heartbeat_interval = 15
        heartbeat_timeout = 30  # 30s timeout for heartbeat response
        
        while True:
            await asyncio.sleep(heartbeat_interval)
            current_time = time.time()
            
            # Check for stale connections
            stale = []
            for conn in list(self.active_connections):
                if conn in last_heartbeat and (current_time - last_heartbeat[conn]) > heartbeat_timeout:
                    stale.append(conn)
            
            # Close stale connections
            for conn in stale:
                try:
                    await conn.close(code=1000, reason="Heartbeat timeout")
                except Exception:
                    pass
                await self.disconnect(conn)
            
            # Send heartbeat to active connections
            if self.active_connections:
                ping = json.dumps({"type": "HEARTBEAT", "ts": datetime.now().isoformat()})
                tasks = []
                for conn in list(self.active_connections):
                    tasks.append(self._safe_send(conn, ping))
                    last_heartbeat[conn] = current_time
                
                await asyncio.gather(*tasks, return_exceptions=True)
                await self.broadcast({"type": "TELEMETRY_HEALTH", "payload": self.telemetry_health_cache})

manager = ConnectionManager()


def _open_sqlite_conn(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    conn.execute('PRAGMA busy_timeout=5000;')
    return conn


def _fetch_telemetry_health_sync(url: str) -> Dict:
    with urllib.request.urlopen(url, timeout=1.5) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


async def poll_telemetry_health(url: str):
    while True:
        try:
            data = await asyncio.to_thread(_fetch_telemetry_health_sync, url)
            if isinstance(data, dict):
                data["ts_ms"] = int(time.time() * 1000)
                manager.telemetry_health_cache = data
        except Exception as exc:
            manager.telemetry_health_cache = {
                "status": "DEGRADED",
                "reason": f"Telemetry endpoint unavailable: {exc}",
                "ts_ms": int(time.time() * 1000),
            }

        await asyncio.sleep(2)

# --- Telemetry & Feedback Loggers ---
def log_to_ledger(agent_name: str, finding_type: str, content: str):
    try:
        conn = _open_sqlite_conn(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agent_logs (agent_name, timestamp, finding_type, content) VALUES (?, ?, ?, ?)",
            (agent_name, datetime.now().isoformat(), finding_type, str(content)[:1000])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

# --- Agent Bus Bridge ---
def on_fusion_alert(payload):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast({
                "channel": "SENTINEL_FUSION_ALERT",
                "payload": payload,
                "timestamp": datetime.now().isoformat()
            }))
    except Exception:
        pass

bus.subscribe("LEGAL_ALERT_GENERATED", on_fusion_alert, name="IndustrialWSBridge")
bus.subscribe("YOLO_DETECTION", on_fusion_alert, name="IndustrialWSBridge")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(manager.heartbeat())
    telemetry_url = os.getenv("SENTINEL_TELEMETRY_URL", "http://127.0.0.1:8000/api/telemetry/health")
    asyncio.create_task(poll_telemetry_health(telemetry_url))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    success = await manager.connect(websocket)
    if not success: return
    client_ip = websocket.client.host

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except: continue

            m_type = message.get("type")
            
            if m_type == "AUTH_HANDSHAKE":
                nonce = message.get("nonce")
                version = message.get("version", "0.0.0")
                f_id = message.get("fleetId", "DEFAULT_FLEET")
                now_ms = int(time.time() * 1000)
                is_replay = (nonce is None) or (abs(now_ms - nonce) > 60000)
                
                if message.get("secret") == DASHBOARD_SECRET_KEY and not is_replay and version == "1.4.0":
                    manager.authed_connections.add(websocket)
                    manager.fleet_health[websocket] = {"node_id": message.get("nodeId"), "fleet_id": f_id}
                    manager.fleet_tenants[websocket] = f_id
                    await websocket.send_json({"type": "AUTH_SUCCESS", "version": "1.4.0"})
                else:
                    # 🛡️ SECURITY: IP Lockout (TC9)
                    manager.failed_auth_counts[client_ip] = manager.failed_auth_counts.get(client_ip, 0) + 1
                    if manager.failed_auth_counts[client_ip] >= 5:
                        manager.blacklisted_ips.add(client_ip)
                    await websocket.send_json({"type": "AUTH_FAILED"})
                    await websocket.close(code=4003)
                    break
            
            elif m_type == "LITE_SOS" and websocket in manager.authed_connections:
                node = message.get("nodeId", "Unknown")
                log_to_ledger("Sentinel-SOS", "PRIORITY_GPS", f"NODE: {node} @ {message.get('lat')},{message.get('lon')}")
            
            elif m_type == "COLLISION_ALERT" and websocket in manager.authed_connections:
                await websocket.send_json({"type": "SOS_RECEIVED", "ts": datetime.now().isoformat()})
                log_to_ledger("Sentinel-SOS", "CRITICAL_COLLISION", f"NODE: {message.get('nodeId')} | IMPACT: {message.get('force')}G")
            
            elif m_type == "HEARTBEAT" and websocket in manager.authed_connections:
                manager.fleet_health[websocket].update({"battery": f"{message.get('battery')}%", "last_seen": datetime.now().isoformat()})
            
            elif m_type == "SENTINEL_FUSION_ALERT" and websocket in manager.authed_connections:
                payload = message.get("payload", {})
                lat, lon = payload.get("lat", 0), payload.get("lon", 0)
                h_type = payload.get("type", "UNKNOWN")
                f_id = manager.fleet_tenants.get(websocket, "DEFAULT_FLEET")
                
                is_duplicate = False
                now = time.time()
                for prev in manager.recent_hazards:
                    if prev['type'] == h_type and get_distance(lat, lon, prev['lat'], prev['lon']) < 50:
                        if now - prev['ts'] < 60:
                            is_duplicate = True
                            break
                
                if not is_duplicate:
                    manager.recent_hazards.append({'lat': lat, 'lon': lon, 'type': h_type, 'ts': now, 'fleet': f_id})
                    manager.recent_hazards = manager.recent_hazards[-100:]
                    log_to_ledger("Sentinel-Fusion", "VERIFIED_HAZARD", f"TYPE: {h_type} @ {lat},{lon}")
                    await manager.broadcast({
                        "channel": "SENTINEL_FUSION_ALERT",
                        "payload": payload,
                        "timestamp": datetime.now().isoformat()
                    }, fleet_id=f_id)

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:
        # D002 FIX: Log unhandled exceptions properly
        logger = logging.getLogger("WebSocketHandler")
        logger.exception(f"Unhandled exception in WebSocket handler: {exc}", exc_info=True)
        await manager.disconnect(websocket)

@app.post("/api/fleet/halt")
async def global_halt(authorization: Optional[str] = Header(default=None)):
    # 🚨 TC50: Global Safety Halt
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token and hmac.compare_digest(token, FLEET_HALT_TOKEN):
        await manager.broadcast({"type": "GLOBAL_HALT", "msg": "Safety Emergency Halt Issued."})
        return {"status": "HALT_ISSUED"}
    return {"status": "UNAUTHORIZED"}

def get_db_connection():
    conn = _open_sqlite_conn(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_predictive_db_connection():
    conn = _open_sqlite_conn(PREDICTIVE_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class CheckoutRequest(BaseModel):
    customer_email: str
    company_name: Optional[str] = None


def generate_api_key() -> str:
    return f"rti_{secrets.token_urlsafe(32)}"


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _upsert_customer(conn: sqlite3.Connection, email: str, company_name: Optional[str]) -> int:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO b2b_customers (email, company_name, created_at, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(email) DO UPDATE SET
            company_name = COALESCE(excluded.company_name, b2b_customers.company_name),
            updated_at = CURRENT_TIMESTAMP
        """,
        (email, company_name),
    )
    cursor.execute("SELECT id FROM b2b_customers WHERE email = ?", (email,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to persist customer")
    return int(row[0])


def _store_api_key(
    conn: sqlite3.Connection,
    customer_id: int,
    api_key: str,
    tier: str = "fleet_pass_24h",
):
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    conn.execute(
        """
        INSERT INTO api_keys (key_hash, customer_id, tier, status, created_at, expires_at)
        VALUES (?, ?, ?, 'active', CURRENT_TIMESTAMP, ?)
        """,
        (_hash_api_key(api_key), customer_id, tier, expires_at),
    )


def require_premium_api_key(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    presented_key = authorization.split(" ", 1)[1].strip()
    if not presented_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key missing")

    key_hash = _hash_api_key(presented_key)
    conn = get_predictive_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ak.customer_id, ak.tier, ak.status, ak.expires_at, bc.email, bc.company_name
        FROM api_keys ak
        JOIN b2b_customers bc ON bc.id = ak.customer_id
        WHERE ak.key_hash = ?
        ORDER BY ak.id DESC
        LIMIT 1
        """,
        (key_hash,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None or row["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key inactive or unknown")

    expires_at = row["expires_at"]
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) < datetime.utcnow():
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key expired")
        except ValueError:
            pass

    return {
        "customer_id": row["customer_id"],
        "tier": row["tier"],
        "email": row["email"],
        "company_name": row["company_name"],
    }


def _extract_customer_email(payload_obj: Dict) -> str:
    payment_entity = payload_obj.get("payload", {}).get("payment", {}).get("entity", {})
    order_entity = payload_obj.get("payload", {}).get("order", {}).get("entity", {})

    candidates = [
        payment_entity.get("email"),
        payment_entity.get("notes", {}).get("customer_email"),
        order_entity.get("notes", {}).get("customer_email"),
    ]
    for value in candidates:
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return ""


@app.post("/api/v1/checkout")
async def checkout_fleet_pass(body: CheckoutRequest):
    email = body.customer_email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid customer_email")

    try:
        order = create_fleet_pass_order(email)
    except PaymentGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    conn = get_predictive_db_connection()
    customer_id = _upsert_customer(conn, email, body.company_name)
    conn.commit()
    conn.close()

    return {
        "message": "Razorpay order created",
        "order": order,
        "customer_id": customer_id,
        "amount_inr": 999,
        "tier": "fleet_pass_24h",
    }


@app.post("/api/v1/webhook/razorpay")
async def razorpay_webhook(request: Request):
    payload_bytes = await request.body()
    payload = payload_bytes.decode("utf-8")
    signature = request.headers.get("x-razorpay-signature", "")

    if not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature header")

    try:
        verify_razorpay_signature(payload, signature)
    except SignatureVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature") from exc
    except PaymentGatewayError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    payload_obj = json.loads(payload)
    event_type = payload_obj.get("event", "")
    if event_type not in {"payment.captured", "order.paid"}:
        return {"status": "ignored", "event": event_type}

    payment_entity = payload_obj.get("payload", {}).get("payment", {}).get("entity", {})
    tx_id = payment_entity.get("id") or payment_entity.get("order_id")
    amount = float(payment_entity.get("amount", 0)) / 100.0
    customer_email = _extract_customer_email(payload_obj)

    if not tx_id or not customer_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tx_id or customer email in webhook")

    api_key = generate_api_key()

    conn = get_predictive_db_connection()
    try:
        # D004 FIX: Begin explicit transaction with rollback on errors
        conn.execute("BEGIN")
        customer_id = _upsert_customer(conn, customer_email, None)
        conn.execute(
            """
            INSERT OR REPLACE INTO transactions (tx_id, customer_id, amount, gateway_signature, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (tx_id, customer_id, amount if amount > 0 else 999.0, signature),
        )
        _store_api_key(conn, customer_id, api_key)
        conn.execute("COMMIT")
    except Exception as webhook_error:
        # Rollback on any error
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass  # Ignore rollback errors
        logging.getLogger("WebhookHandler").exception(
            f"Transaction failed for payment {tx_id}, rolling back",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment processing failed"
        ) from webhook_error
    finally:
        conn.close()

    response_payload = {
        "status": "success",
        "tx_id": tx_id,
        "customer_email": customer_email,
        "tier": "fleet_pass_24h",
    }
    if os.getenv("RETURN_API_KEY_IN_WEBHOOK", "false").strip().lower() in {"1", "true", "yes", "on"}:
        response_payload["api_key"] = api_key
    return response_payload


@app.post("/api/v1/api-key/revoke")
async def revoke_api_key(
    request: Request,
    api_key: str = None,
    premium_customer: Dict = Depends(require_premium_api_key),
):
    """V031 FIX: API key revocation endpoint for security control."""
    if not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="api_key required")
    
    conn = get_predictive_db_connection()
    try:
        conn.execute("BEGIN")
        # Find the API key owner
        cursor = conn.execute(
            "SELECT customer_id FROM api_keys WHERE key_hash = ?",
            (hashlib.sha256(api_key.encode()).hexdigest(),)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
        
        # Verify ownership: only the key owner or admin can revoke
        key_customer_id = row[0]
        if premium_customer["customer_id"] != key_customer_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to revoke this key")
        
        # Revoke the key by setting revoked_at timestamp
        conn.execute(
            "UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP WHERE key_hash = ?",
            (hashlib.sha256(api_key.encode()).hexdigest(),)
        )
        conn.execute("COMMIT")
        return {"status": "revoked", "message": "API key successfully revoked"}
    except HTTPException:
        raise
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        logging.getLogger("APIKeyHandler").exception("Key revocation failed", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Revocation failed") from exc
    finally:
        conn.close()


@app.get("/api/v1/fleet-routing-hazards")
def get_fleet_routing_hazards(
    premium_customer: Dict = Depends(require_premium_api_key),
    min_score: float = 0.35,
    hotspot_limit: int = 100,
    hazard_limit: int = 200,
):
    pred_conn = get_predictive_db_connection()
    pred_cursor = pred_conn.cursor()

    pred_cursor.execute(
        """
        SELECT
            grid_id,
            center_lat,
            center_lon,
            road_type,
            report_count,
            verified_report_count,
            accident_signal_count,
            danger_probability_score,
            status,
            first_seen_at,
            last_seen_at,
            metadata
        FROM predictive_hotspots
        WHERE status = 'active' AND danger_probability_score >= ?
        ORDER BY danger_probability_score DESC, verified_report_count DESC
        LIMIT ?
        """,
        (max(0.0, min(1.0, min_score)), max(1, min(2000, hotspot_limit))),
    )
    hotspots = [dict(r) for r in pred_cursor.fetchall()]

    for row in hotspots:
        if isinstance(row.get("metadata"), str):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except Exception:
                pass

    pred_cursor.execute(
        """
        SELECT
            event_id,
            event_type,
            vehicle_h3_cell,
            blackspot_h3_cell,
            severity,
            metadata,
            timestamp
        FROM event_log
        WHERE (
            event_type LIKE '%hazard%'
            OR event_type IN ('YOLO_DETECTION', 'SENTINEL_FUSION_ALERT', 'VERIFIED_HAZARD')
        )
        AND (severity IS NULL OR severity >= 0.75)
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (max(1, min(2000, hazard_limit)),),
    )
    swarm_hazards = [dict(r) for r in pred_cursor.fetchall()]
    pred_conn.close()

    for row in swarm_hazards:
        if isinstance(row.get("metadata"), str):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except Exception:
                pass

    return {
        "customer": premium_customer,
        "predictive_hotspots": hotspots,
        "swarm_hazards": swarm_hazards,
        "counts": {
            "predictive_hotspots": len(hotspots),
            "swarm_hazards": len(swarm_hazards),
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

@app.get("/api/agent2/findings")
def get_agent2_findings(limit: int = 20):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, agent_name, timestamp, finding_type, content FROM agent_logs WHERE agent_name LIKE 'Sentinel%' OR agent_name = 'Agent2-ModelScout' ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return {"findings": [dict(r) for r in rows]}

@app.get("/api/agent2/stats")
def get_agent2_stats():
    return {
        "fleet_nodes": len(manager.authed_connections),
        "version": "1.4.0-Absolute",
        "blacklist_size": len(manager.blacklisted_ips)
    }


@app.get("/api/precog/hotspots")
def get_predictive_hotspots(limit: int = 100, min_score: float = 0.35):
    conn = get_predictive_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id,
            grid_id,
            center_lat,
            center_lon,
            road_type,
            report_count,
            verified_report_count,
            accident_signal_count,
            danger_probability_score,
            status,
            first_seen_at,
            last_seen_at,
            metadata,
            rti_status
        FROM predictive_hotspots
        WHERE danger_probability_score >= ?
        ORDER BY danger_probability_score DESC, verified_report_count DESC
        LIMIT ?
        """,
        (max(0.0, min(1.0, min_score)), max(1, min(2000, limit))),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for row in rows:
        if isinstance(row.get("metadata"), str):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except Exception:
                pass

    return {"hotspots": rows, "count": len(rows)}

@app.get("/api/all_agents/summary")
def get_all_agents_summary():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT agent_name, COUNT(*) as cnt, MAX(timestamp) as last_seen FROM agent_logs GROUP BY agent_name ORDER BY last_seen DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"agents": [dict(r) for r in rows]}


@app.get("/api/telemetry/health")
def get_telemetry_health():
    return manager.telemetry_health_cache

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    html_file = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    import uvicorn
    from core.tls_config import TLSConfig

    tls_config = TLSConfig()
    if tls_config.use_https:
        tls_config.validate()
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8765,
            reload=False,
            ssl_certfile=tls_config.cert_path,
            ssl_keyfile=tls_config.key_path,
        )
    else:
        uvicorn.run(app, host="0.0.0.0", port=8765, reload=False)
