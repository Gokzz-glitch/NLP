def get_jurisdiction(lat, lon, db_path="edge_spatial.db"):
    """
    Reverse geocode (lat, lon) to nearest road segment in osm_roads (within 50m), map to authority.
    Returns: dict with highway, ref, name, authority, road_type, distance_m
    """
    import sqlite3
    import math
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 15000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.enable_load_extension(True)
    try:
        conn.load_extension("mod_spatialite")
    except Exception:
        try:
            conn.load_extension("spatialite")
        except Exception:
            pass
    cursor = conn.cursor()
    # Ensure jurisdiction table exists
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jurisdiction (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        lat REAL,
        lon REAL
    );
    """)
    # WKT point
    point_wkt = f"POINT({lon} {lat})"
    # Find nearest road within 50m
    cursor.execute(
        """
        SELECT osm_id, highway, ref, name, ST_Distance(geom, ST_GeomFromText(?, 4326)) as dist
        FROM osm_roads
        WHERE ST_DWithin(geom, ST_GeomFromText(?, 4326), 0.00045) -- ~50m in degrees
        ORDER BY dist ASC LIMIT 1
        """,
        (point_wkt, point_wkt)
    )
    row = cursor.fetchone()
    if not row:
        return {"authority": "UNKNOWN", "road_type": None, "distance_m": None}
    highway = row[1]
    ref = row[2]
    name = row[3]
    dist = row[4]
    # Convert degrees to meters (roughly)
    distance_m = dist * 111320 if dist is not None else None
    # Map highway tag to authority
    if highway == "trunk":
        authority = "NHAI"
        road_type = "National Highway"
    elif highway == "primary":
        authority = "State Highways Department"
        road_type = "State Highway"
    elif highway == "secondary":
        authority = "PWD"
        road_type = "Major District Road"
    elif highway == "residential":
        authority = "Local Municipality"
        road_type = "Local Road"
    else:
        authority = "UNKNOWN"
        road_type = highway
    return {
        "highway": highway,
        "ref": ref,
        "name": name,
        "authority": authority,
        "road_type": road_type,
        "distance_m": distance_m,
    }
import asyncio
import websockets
import json
import logging
import time
import statistics
import os
import sqlite3
import hmac
import struct
from collections import deque
from pathlib import Path
from typing import Any
import threading
import uuid
import hashlib
from core.agent_bus import bus
from core.secret_manager import get_manager

# [PERSONA 7: THE BRIDGE / CLOUD SYNC]
# Task: T-041 — WebSocket bridge for the Mobile Frontend.

logger = logging.getLogger("edge_sentinel.api_bridge")
logger.setLevel(logging.INFO)

class APIBridgeAgent:
    """
    Exposes the internal AgentBus over WebSocket (ws://) so that the React Native 
    mobile app can receive live hazard telemetry and stream IMU data back into the system.
    """
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: set = set()
        self.loop = asyncio.new_event_loop()
        self._bridge_age_ms = deque(maxlen=500)
        self._broadcast_ms = deque(maxlen=500)
        self._e2e_roundtrip_ms = deque(maxlen=500)
        self._pending_alert_origin_ms = {}
        self._seen_messages = {}
        self._forward_count = 0
        self._watchdog_tick = 0
        self._target_inference_fps = 15
        self._min_inference_fps = 5
        self._max_inference_fps = 15
        self._thermal_throttled = False
        self._seen_limit = int(os.getenv("API_BRIDGE_SEEN_LIMIT", "12000"))
        self._pending_limit = int(os.getenv("API_BRIDGE_PENDING_LIMIT", "12000"))
        self._broadcast_spike_ms = float(os.getenv("API_BRIDGE_BROADCAST_SPIKE_MS", "40.0"))
        self._dedup_window_ms = int(os.getenv("API_BRIDGE_DEDUP_WINDOW_MS", "1500"))
        self._housekeeping_every_ticks = int(os.getenv("API_BRIDGE_HOUSEKEEPING_EVERY_TICKS", "20"))
        self._seen_trim_ratio = float(os.getenv("API_BRIDGE_SEEN_TRIM_RATIO", "0.35"))
        self._pending_trim_ratio = float(os.getenv("API_BRIDGE_PENDING_TRIM_RATIO", "0.4"))
        self._telemetry_file = Path("logs") / "telemetry_health.json"
        self._spatial_db_path = os.getenv("EDGE_SPATIAL_DB_PATH", "edge_spatial.db")
        
        # Get FERNET_KEY from SecretManager
        sm = get_manager(strict_mode=False)
        fernet_key = sm.get("FERNET_KEY")
        if not fernet_key:
            raise RuntimeError(
                "FERNET_KEY environment variable not set. "
                "Required for BLE payload encryption."
            )
        self._swarm_secret = fernet_key.encode()
        
        self._swarm_fast_trust_rank = int(os.getenv("SWARM_FAST_TRACK_TRUST_RANK", "5"))
        self._setup_bus()

    def _open_gamification_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._spatial_db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _verify_ble_payload(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False

        # Format A: direct BLE advertisement frame with hex payload + 4-byte HMAC suffix.
        if payload.get("hex"):
            try:
                raw = bytes.fromhex(payload["hex"])
                if len(raw) < 5:
                    return False
                body, signature = raw[:-4], raw[-4:]
                expected = hmac.new(self._swarm_secret, body, hashlib.sha256).digest()[:4]
                return hmac.compare_digest(signature, expected)
            except Exception:
                return False

        # Format B: JSON payload with explicit signature over canonicalized payload block.
        envelope = payload.get("payload", payload)
        if not isinstance(envelope, dict):
            return False

        signature = envelope.get("signature") or payload.get("signature")
        if not signature:
            return False

        signed_data = dict(envelope)
        signed_data.pop("signature", None)
        canonical = json.dumps(signed_data, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(self._swarm_secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        return hmac.compare_digest(str(signature).lower(), expected.lower())

    def _extract_reporter_id(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "UNKNOWN_REPORTER"

        nested_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        return (
            payload.get("user_id")
            or payload.get("reporter_id")
            or payload.get("origin_node")
            or nested_payload.get("origin_node")
            or payload.get("node_id")
            or "UNKNOWN_REPORTER"
        )

    def _reward_verified_report(self, reporter_id: str) -> dict:
        conn = self._open_gamification_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    safety_tokens INTEGER NOT NULL DEFAULT 0,
                    trust_rank INTEGER NOT NULL DEFAULT 0,
                    verified_report_count INTEGER NOT NULL DEFAULT 0,
                    last_report_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO users (user_id, safety_tokens, trust_rank, verified_report_count, last_report_at, updated_at)
                VALUES (?, 10, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    safety_tokens = users.safety_tokens + 10,
                    trust_rank = users.trust_rank + 1,
                    verified_report_count = users.verified_report_count + 1,
                    last_report_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (reporter_id,),
            )
            conn.commit()
            cursor.execute(
                "SELECT user_id, safety_tokens, trust_rank, verified_report_count, last_report_at FROM users WHERE user_id = ?",
                (reporter_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return {}
            return {
                "user_id": row[0],
                "safety_tokens": row[1],
                "trust_rank": row[2],
                "verified_report_count": row[3],
                "last_report_at": row[4],
            }
        finally:
            conn.close()

    def _log_verified_swarm_event(self, reporter_id: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        lat = payload.get("lat")
        lon = payload.get("lon")
        if lat is None or lon is None:
            nested = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
            data_block = nested.get("data", {}) if isinstance(nested.get("data"), dict) else {}
            location = data_block.get("location", {}) if isinstance(data_block.get("location"), dict) else {}
            lat = location.get("lat", lat)
            lon = location.get("lon", lon)

        conn = self._open_gamification_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO event_log (event_type, event_id, severity, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "verified_swarm_report",
                    payload.get("event_id") or payload.get("alert_id") or str(uuid.uuid4()),
                    float(payload.get("severity", 0.5)) if isinstance(payload.get("severity", 0.5), (int, float)) else 0.5,
                    json.dumps(
                        {
                            "reporter_id": reporter_id,
                            "lat": lat,
                            "lon": lon,
                            "road_type": payload.get("road_type"),
                            "channel_payload_type": payload.get("type"),
                        }
                    ),
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("API_BRIDGE_WARN: Failed to log verified swarm event: %s", exc)
        finally:
            conn.close()

    def _maybe_reward_ble_report(self, channel: str, payload: Any) -> dict:
        if channel not in {"PHYSICAL_BLE_ADVERTISEMENT", "BLE_SWARM_REPORT", "BLE_HAZARD_PAYLOAD"}:
            return {}

        if not self._verify_ble_payload(payload):
            logger.warning("API_BRIDGE_SECURITY: Rejected invalid BLE payload on channel=%s", channel)
            return {}

        reporter_id = self._extract_reporter_id(payload)
        user_state = self._reward_verified_report(reporter_id)
        self._log_verified_swarm_event(reporter_id, payload)
        if user_state:
            bus.emit("SWARM_REPORT_VERIFIED", {
                "reporter_id": reporter_id,
                "trust_rank": user_state.get("trust_rank", 0),
                "safety_tokens": user_state.get("safety_tokens", 0),
                "ts_ms": int(time.time() * 1000),
            })
        return user_state
        
    def _setup_bus(self):
        # Forward these critical channels to the frontend UI
        channels = [
            "FAST_CRITICAL_ALERT",
            "SENTINEL_FUSION_ALERT",
            "VOICE_ALERT_REQUEST",
            "TTS_SYNTHESIS_REQUEST",
            "REGULATORY_CONFLICT",
            "VISION_HAZARD_DETECTED",
            "NEAR_MISS_DETECTED",
        ]
        for ch in channels:
            bus.subscribe(ch, lambda pl, channel=ch: self._forward_to_mobile(channel, pl))

    @staticmethod
    def _percentile(values, p):
        if not values:
            return 0.0
        idx = int(round((p / 100.0) * (len(values) - 1)))
        idx = max(0, min(idx, len(values) - 1))
        return values[idx]

    def get_telemetry_health(self):
        bridge_age = sorted(self._bridge_age_ms)
        broadcast = sorted(self._broadcast_ms)
        roundtrip = sorted(self._e2e_roundtrip_ms)

        return {
            "ts_ms": int(time.time() * 1000),
            "samples": {
                "bridge_age": len(bridge_age),
                "broadcast": len(broadcast),
                "e2e_roundtrip": len(roundtrip),
            },
            "bridge_latency_ms": {
                "p50": self._percentile(bridge_age, 50),
                "p95": self._percentile(bridge_age, 95),
                "p99": self._percentile(bridge_age, 99),
                "mean": statistics.mean(bridge_age) if bridge_age else 0.0,
            },
            "bridge_broadcast_ms": {
                "p50": self._percentile(broadcast, 50),
                "p95": self._percentile(broadcast, 95),
                "p99": self._percentile(broadcast, 99),
                "mean": statistics.mean(broadcast) if broadcast else 0.0,
            },
            "e2e_roundtrip_ms": {
                "p50": self._percentile(roundtrip, 50),
                "p95": self._percentile(roundtrip, 95),
                "p99": self._percentile(roundtrip, 99),
                "mean": statistics.mean(roundtrip) if roundtrip else 0.0,
            },
            "adaptive_control": {
                "thermal_throttled": self._thermal_throttled,
                "target_inference_fps": self._target_inference_fps,
                "seen_messages": len(self._seen_messages),
                "pending_alerts": len(self._pending_alert_origin_ms),
            },
        }

    def _is_duplicate(self, channel: str, payload: Any, now_ms: int) -> bool:
        if not isinstance(payload, dict):
            return False

        if int(payload.get("trust_rank", 0)) >= self._swarm_fast_trust_rank:
            return False

        unique_key = payload.get("alert_id") or payload.get("fusion_id") or payload.get("event_id")
        if unique_key is None:
            raw = json.dumps(payload, sort_keys=True, default=str)
            unique_key = hashlib.md5(raw.encode("utf-8")).hexdigest()

        fingerprint = f"{channel}:{unique_key}"
        last_seen = self._seen_messages.get(fingerprint)
        self._seen_messages[fingerprint] = now_ms

        # Deduplicate repeated non-critical payloads in configurable short window.
        if channel not in {"FAST_CRITICAL_ALERT", "SENTINEL_FUSION_ALERT"} and last_seen and (now_ms - last_seen) < self._dedup_window_ms:
            return True
        return False

    def _watchdog_housekeeping(self):
        self._watchdog_tick += 1
        if self._watchdog_tick % self._housekeeping_every_ticks != 0:
            return

        now_ms = int(time.time() * 1000)

        # Trim stale seen-message fingerprints.
        stale_keys = [k for k, ts in self._seen_messages.items() if (now_ms - ts) > 120000]
        for key in stale_keys:
            self._seen_messages.pop(key, None)

        if len(self._seen_messages) > self._seen_limit:
            # OOM shield: drop oldest seen cache entries.
            ordered = sorted(self._seen_messages.items(), key=lambda x: x[1])
            trim_count = max(1, int(len(ordered) * self._seen_trim_ratio))
            for key, _ in ordered[:trim_count]:
                self._seen_messages.pop(key, None)
            logger.warning("API_BRIDGE_OOM_GUARD: Trimmed seen-message cache under pressure.")

        if len(self._pending_alert_origin_ms) > self._pending_limit:
            # Queue flush under memory pressure.
            ordered_pending = list(self._pending_alert_origin_ms.items())
            ordered_pending.sort(key=lambda x: x[1])
            trim_count = max(1, int(len(ordered_pending) * self._pending_trim_ratio))
            for key, _ in ordered_pending[:trim_count]:
                self._pending_alert_origin_ms.pop(key, None)
            logger.warning("API_BRIDGE_OOM_GUARD: Flushed pending alert cache under pressure.")

        broadcast_sorted = sorted(self._broadcast_ms)
        p95_broadcast = self._percentile(broadcast_sorted, 95)

        if p95_broadcast > self._broadcast_spike_ms:
            self._thermal_throttled = True
            self._target_inference_fps = max(self._min_inference_fps, self._target_inference_fps - 2)
            bus.emit("SYSTEM_PERF_DOWNSHIFT", {
                "source": "APIBridgeAgent",
                "reason": "thermal_spike",
                "p95_broadcast_ms": p95_broadcast,
                "target_inference_fps": self._target_inference_fps,
                "ts_ms": now_ms,
            })
        elif self._thermal_throttled and p95_broadcast < (self._broadcast_spike_ms * 0.6):
            self._target_inference_fps = min(self._max_inference_fps, self._target_inference_fps + 1)
            if self._target_inference_fps >= self._max_inference_fps:
                self._thermal_throttled = False
            bus.emit("SYSTEM_PERF_RECOVERY", {
                "source": "APIBridgeAgent",
                "p95_broadcast_ms": p95_broadcast,
                "target_inference_fps": self._target_inference_fps,
                "ts_ms": now_ms,
            })

    def _write_telemetry_snapshot(self):
        try:
            self._telemetry_file.parent.mkdir(parents=True, exist_ok=True)
            self._telemetry_file.write_text(json.dumps(self.get_telemetry_health(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"API_BRIDGE_WARN: Failed to write telemetry snapshot: {e}")

    def _register_pending_alert(self, payload: dict):
        if "alert_id" not in payload:
            payload["alert_id"] = str(uuid.uuid4())

        origin_ms = payload.get("origin_timestamp_ms", payload.get("_event_ts_ms"))
        if isinstance(origin_ms, (int, float)):
            self._pending_alert_origin_ms[payload["alert_id"]] = float(origin_ms)

    def _record_ack(self, payload: Any):
        if not isinstance(payload, dict):
            return

        ack_ts = payload.get("ack_timestamp_ms")
        alert_id = payload.get("alert_id")
        origin_ts = payload.get("origin_timestamp_ms")

        if not isinstance(origin_ts, (int, float)) and alert_id:
            origin_ts = self._pending_alert_origin_ms.get(alert_id)

        if isinstance(ack_ts, (int, float)) and isinstance(origin_ts, (int, float)):
            delta_ms = float(ack_ts) - float(origin_ts)
            if delta_ms >= 0:
                self._e2e_roundtrip_ms.append(delta_ms)

            if alert_id:
                self._pending_alert_origin_ms.pop(alert_id, None)
            
    def _forward_to_mobile(self, channel: str, payload: Any):
        """Called by Python synchronous bus -> pushes to WebSocket clients"""
        if not self.clients:
            return
            
        try:
            now_ms = int(time.time() * 1000)
            if isinstance(payload, dict):
                bridged_payload = dict(payload)
            else:
                bridged_payload = {"data": payload}

            self._watchdog_housekeeping()

            if self._is_duplicate(channel, bridged_payload, now_ms):
                return

            # Preserve original payload and attach bridge timing for client-side latency accounting.
            bridged_payload.setdefault("origin_timestamp_ms", now_ms)
            bridged_payload.setdefault("_event_ts_ms", now_ms)
            bridged_payload["_bridge_tx_ts_ms"] = now_ms
            bridged_payload["_channel_priority"] = "high" if channel == "FAST_CRITICAL_ALERT" else "normal"

            if channel in {"FAST_CRITICAL_ALERT", "SENTINEL_FUSION_ALERT"}:
                self._register_pending_alert(bridged_payload)

            if channel == "ALERT_RECEIVED_ACK":
                self._record_ack(bridged_payload)

            event_ts_ms = bridged_payload.get("_event_ts_ms")
            if isinstance(event_ts_ms, (int, float)):
                self._bridge_age_ms.append(max(0.0, float(now_ms - event_ts_ms)))

            message = json.dumps({
                "channel": channel,
                "payload": bridged_payload
            }, default=lambda o: getattr(o, '__dict__', str(o)))
            
            # Schedule the coroutine in the background asyncio loop
            fut = asyncio.run_coroutine_threadsafe(self._broadcast(message), self.loop)
            fut.add_done_callback(self._on_broadcast_done)

            self._forward_count += 1
            if self._forward_count % 100 == 0:
                self._log_latency_snapshot()
                self._write_telemetry_snapshot()
        except Exception as e:
            logger.error(f"API_BRIDGE_ERROR: Serialization failed: {e}")

    def _log_latency_snapshot(self):
        if not self._bridge_age_ms and not self._broadcast_ms:
            return

        age_sorted = sorted(self._bridge_age_ms)
        br_sorted = sorted(self._broadcast_ms)
        rt_sorted = sorted(self._e2e_roundtrip_ms)

        logger.info(
            "API_BRIDGE_LATENCY: bridge_age_ms[p50=%.1f p95=%.1f p99=%.1f] "
            "broadcast_ms[p50=%.2f p95=%.2f p99=%.2f mean=%.2f] "
            "e2e_roundtrip_ms[p50=%.1f p95=%.1f p99=%.1f]",
            self._percentile(age_sorted, 50),
            self._percentile(age_sorted, 95),
            self._percentile(age_sorted, 99),
            self._percentile(br_sorted, 50),
            self._percentile(br_sorted, 95),
            self._percentile(br_sorted, 99),
            statistics.mean(br_sorted) if br_sorted else 0.0,
            self._percentile(rt_sorted, 50),
            self._percentile(rt_sorted, 95),
            self._percentile(rt_sorted, 99),
        )

    def _on_broadcast_done(self, fut):
        try:
            fut.result()
        except Exception as e:
            logger.error(f"API_BRIDGE_ERROR: Broadcast failed: {e}")

    async def _broadcast(self, message: str):
        if not self.clients:
            return

        started = time.perf_counter()
        clients_snapshot = list(self.clients)
        results = await asyncio.gather(
            *[client.send(message) for client in clients_snapshot],
            return_exceptions=True,
        )
        self._broadcast_ms.append((time.perf_counter() - started) * 1000.0)

        for client, result in zip(clients_snapshot, results):
            if isinstance(result, Exception):
                logger.warning(f"API_BRIDGE_WARN: Dropping slow/disconnected client: {result}")
                self.clients.discard(client)

    async def _serve(self):
        async with websockets.serve(
            self._handler,
            self.host,
            self.port,
            ping_interval=15,
            ping_timeout=10,
            max_queue=64,
        ):
            logger.info(f"PERSONA_7_REPORT: API_BRIDGE_ONLINE | ws://{self.host}:{self.port}")
            await asyncio.Future()

    async def _handler(self, websocket):
        self.clients.add(websocket)
        logger.info(f"MOBILE_APP_CONNECTED | Total clients: {len(self.clients)}")
        try:
            async for message in websocket:
                # App streams sensor data up to Python (e.g. IMU samples)
                data = json.loads(message)
                if "channel" in data and "payload" in data:
                    payload = data["payload"]
                    if isinstance(payload, dict):
                        payload.setdefault("origin_timestamp_ms", int(time.time() * 1000))

                    user_state = self._maybe_reward_ble_report(data["channel"], payload)
                    if user_state and isinstance(payload, dict):
                        trust_rank = int(user_state.get("trust_rank", 0))
                        payload["reporter_id"] = user_state.get("user_id")
                        payload["trust_rank"] = trust_rank
                        payload["safety_tokens"] = int(user_state.get("safety_tokens", 0))
                        payload["swarm_priority"] = (
                            "expedited" if trust_rank >= self._swarm_fast_trust_rank else "standard"
                        )
                        # Higher-trust reports are emitted with explicit fast-track metadata.
                        if payload["swarm_priority"] == "expedited":
                            payload["priority_boost"] = "trust_rank_fast_lane"

                    if data["channel"] == "ALERT_RECEIVED_ACK":
                        self._record_ack(payload)
                        self._write_telemetry_snapshot()

                    # Inject mobile telemetry directly into the internal bus
                    bus.emit(data["channel"], payload)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"MOBILE_STREAM_ERROR: {e}")
        finally:
            self.clients.discard(websocket)
            logger.info(f"MOBILE_APP_DISCONNECTED | Remaining: {len(self.clients)}")

    def start(self):
        """Starts the WebSocket server in a background thread."""
        def run_server():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._serve())
            
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bridge = APIBridgeAgent()
    bridge.start()
    
    # Keep main thread alive for tests
    import time
    while True:
        time.sleep(1)
