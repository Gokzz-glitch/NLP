import os
import time
import sys
import json
import asyncio
import logging
import statistics
import websockets
from collections import deque
from core.agent_bus import bus
from core.driver_memory import memory

# Configure Orchestrator Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: [MACHA_ORCHESTRATOR] %(message)s")
logger = logging.getLogger("edge_sentinel.orchestrator")

class MachaOrchestrator:
    def __init__(self):
        self.connected_clients = set()
        self.seen_messages = {}
        self.max_seen_messages = 4000
        self.recent_processing_ms = deque(maxlen=300)
        self.target_inference_fps = 15
        self.min_inference_fps = 5
        self.max_inference_fps = 15
        self.thermal_throttled = False
        self.processing_spike_ms = 40.0
        logger.info("MACHA_ORCHESTRATOR: Intelligence Service Initialized.")

    def _fingerprint(self, channel, payload):
        if isinstance(payload, dict):
            key = payload.get("alert_id") or payload.get("fusion_id") or payload.get("event_id")
            if key:
                return f"{channel}:{key}"
        return f"{channel}:{hash(json.dumps(payload, sort_keys=True, default=str))}"

    def _watchdog_housekeeping(self):
        now_ms = int(time.time() * 1000)
        stale = [k for k, ts in self.seen_messages.items() if (now_ms - ts) > 120000]
        for key in stale:
            self.seen_messages.pop(key, None)

        if len(self.seen_messages) > self.max_seen_messages:
            ordered = sorted(self.seen_messages.items(), key=lambda x: x[1])
            for key, _ in ordered[: int(len(ordered) * 0.5)]:
                self.seen_messages.pop(key, None)
            logger.warning("ORCH_OOM_GUARD: seen_messages cache flushed under pressure.")

        proc_sorted = sorted(self.recent_processing_ms)
        p95_proc = 0.0
        if proc_sorted:
            idx = int(round(0.95 * (len(proc_sorted) - 1)))
            p95_proc = proc_sorted[max(0, min(idx, len(proc_sorted) - 1))]

        if p95_proc > self.processing_spike_ms:
            self.thermal_throttled = True
            self.target_inference_fps = max(self.min_inference_fps, self.target_inference_fps - 2)
            bus.emit("SYSTEM_PERF_DOWNSHIFT", {
                "source": "MachaOrchestrator",
                "reason": "processing_spike",
                "p95_processing_ms": p95_proc,
                "target_inference_fps": self.target_inference_fps,
                "ts_ms": now_ms,
            })
        elif self.thermal_throttled and p95_proc < (self.processing_spike_ms * 0.6):
            self.target_inference_fps = min(self.max_inference_fps, self.target_inference_fps + 1)
            if self.target_inference_fps >= self.max_inference_fps:
                self.thermal_throttled = False
            bus.emit("SYSTEM_PERF_RECOVERY", {
                "source": "MachaOrchestrator",
                "p95_processing_ms": p95_proc,
                "target_inference_fps": self.target_inference_fps,
                "ts_ms": now_ms,
            })

    async def broadcast(self, message):
        if self.connected_clients:
            disconnected = set()
            for client in self.connected_clients:
                try:
                    await client.send(json.dumps(message))
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"ORCH_DROP: Client disconnected during broadcast [{e.code}]: {e.reason}")
                    disconnected.add(client)
                except Exception as e:
                    logger.error(f"ORCH_ERROR: Unexpected broadcast failure: {e}")
                    disconnected.add(client)
            self.connected_clients -= disconnected

    async def heartbeat(self):
        while True:
            try:
                # [FIX #5]: Route heartbeat onto agent bus for proper pub-sub decoupling
                bus.emit("SYSTEM_HEARTBEAT", {"status": "ALIVE", "timestamp": time.time()})
                # Also broadcast to WebSocket clients for HUD
                await self.broadcast({"channel": "SYSTEM_HEARTBEAT", "payload": {"status": "ALIVE", "timestamp": time.time()}})
                self._watchdog_housekeeping()
            except Exception as e:
                logger.error(f"HEARTBEAT_ERROR: {e}")
            # [FIX #5]: Use asyncio.sleep (already non-blocking, OK as-is)
            await asyncio.sleep(2)

    async def handler(self, websocket):
        self.connected_clients.add(websocket)
        logger.info(f"BUS_EVENT: CONNECTED: New client from {websocket.remote_address}")
        try:
            async for message in websocket:
                started = time.perf_counter()
                data = json.loads(message)
                channel = data.get("channel")
                payload = data.get("payload", {})
                logger.info(f"RECV: [{channel}]")

                fp = self._fingerprint(channel, payload)
                now_ms = int(time.time() * 1000)
                last_seen = self.seen_messages.get(fp)
                self.seen_messages[fp] = now_ms
                if channel not in {"SENTINEL_FUSION_ALERT", "FAST_CRITICAL_ALERT"} and last_seen and (now_ms - last_seen) < 2000:
                    continue

                if channel == "SENTINEL_FUSION_ALERT":
                    bus.emit("SENTINEL_FUSION_ALERT", payload)
                    await self.broadcast(data)
                elif channel == "DRIVER_MEMORY_UPDATE":
                    event = payload.get("event")
                    score = payload.get("score", 0)
                    memory.log_event(event, score)
                    logger.info(f"MEMORY_SYNC: {event} ({score:+d})")

                processing_ms = (time.perf_counter() - started) * 1000.0
                self.recent_processing_ms.append(processing_ms)
        except Exception as e:
            logger.error(f"BUS_ERROR: {e}")
        finally:
            if websocket in self.connected_clients:
                self.connected_clients.remove(websocket)
            logger.info(f"BUS_EVENT: DISCONNECTED: Client from {websocket.remote_address}")

    async def run(self, host="0.0.0.0", port=8765):
        print(f"\n[SERVICE] MACHA_SERVICE_GATEWAY: Listening on ws://{host}:{port}")
        import agents.acoustic_ui 
        asyncio.create_task(self.heartbeat())
        async with websockets.serve(self.handler, host, port):
            await asyncio.Future()

if __name__ == "__main__":
    orch = MachaOrchestrator()
    try:
        asyncio.run(orch.run())
    except KeyboardInterrupt:
        logger.info("MACHA_ORCHESTRATOR: Shutting down gracefully.")
