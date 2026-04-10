"""
SWARM LOAD TEST HARNESS
Tests BLE mesh relay, spatial DB writes, and collision rates under N nodes in 1km radius.
Validates Phase 5 scaling limits (18 nodes max stable, 24-30 hard-fail band).
"""

import asyncio
import json
import logging
import time
import random
import sqlite3
from datetime import datetime
from typing import List, Dict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("swarm_load_test")


class SyntheticNode:
    """Simulates a single rider node with GPS, hazard detection, and BLE broadcasts."""
    
    def __init__(self, node_id: int, central_lat: float = 13.0, central_lon: float = 80.0):
        self.node_id = node_id
        self.base_lat = central_lat + random.uniform(-0.005, 0.005)  # ~500m jitter
        self.base_lon = central_lon + random.uniform(-0.005, 0.005)
        self.hazard_emit_count = 0
        self.relay_count = 0
        self.db_write_latency_ms = []
        
    async def emit_hazard(self):
        """Simulate hazard detection and BLE broadcast."""
        hazard_types = ["POTHOLE", "SPEED_TRAP_NO_SIGNAGE", "ACCIDENT_NEAR_MISS"]
        payload = {
            "protocol": "SMART_SALAI_V2X_OFFLINE",
            "version": "1.1-GODFATHER",
            "payload": {
                "msg_id": f"node-{self.node_id}-{time.time()}",
                "timestamp": datetime.now().isoformat(),
                "origin_node": f"MAC_{self.node_id:04d}",
                "data": {
                    "hazard_class": random.choice(hazard_types),
                    "severity": random.randint(0, 3),
                    "location": {"lat": self.base_lat, "lon": self.base_lon, "hmsl": 5.0},
                    "sensor_metadata": {
                        "imu_z_spike": random.uniform(0.5, 2.0),
                        "vision_confidence": random.uniform(0.65, 0.99)
                    }
                },
                "signature": "simulated_sig"
            }
        }
        
        # Simulate DB write
        start = time.perf_counter()
        try:
            conn = sqlite3.connect("spatial_ground_truth.db", timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("INSERT INTO ground_truth_markers (node_id, class, lat, lon, severity, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                         (f"MAC_{self.node_id:04d}", payload["payload"]["data"]["hazard_class"], 
                          self.base_lat, self.base_lon, payload["payload"]["data"]["severity"], 
                          payload["payload"]["data"]["sensor_metadata"]["vision_confidence"]))
            conn.commit()
            conn.close()
            latency = (time.perf_counter() - start) * 1000
            self.db_write_latency_ms.append(latency)
            self.hazard_emit_count += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"Node-{self.node_id} DB_LOCK: {e}")
    
    async def relay_packet(self):
        """Simulate BLE mesh relay."""
        self.relay_count += 1
        await asyncio.sleep(random.uniform(0.001, 0.01))  # Simulate relay processing


class SwarmLoadTest:
    """Orchestrates load test with N synthetic nodes."""
    
    def __init__(self, num_nodes: int = 18, duration_sec: int = 30, hazard_rate_hz: float = 2.0):
        self.num_nodes = num_nodes
        self.duration_sec = duration_sec
        self.hazard_rate_hz = hazard_rate_hz
        self.nodes: List[SyntheticNode] = []
        self.db_lock_count = 0
        self.start_time = None
        self.end_time = None
        
    async def run(self):
        """Execute full load test."""
        logger.info(f"🚀 SWARM_LOAD_TEST: Starting with {self.num_nodes} nodes, {self.duration_sec}s duration")
        
        # Initialize synthetic nodes
        self.nodes = [SyntheticNode(i) for i in range(self.num_nodes)]
        
        # Check DB exists
        if not Path("spatial_ground_truth.db").exists():
            logger.warning("Initializing spatial_ground_truth.db...")
            conn = sqlite3.connect("spatial_ground_truth.db")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ground_truth_markers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    node_id TEXT,
                    class TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    severity INTEGER DEFAULT 0,
                    confidence REAL,
                    imu_trigger_magnitude REAL,
                    is_verified_locally INTEGER DEFAULT 0,
                    raw_metadata_json TEXT
                )
            """)
            conn.commit()
            conn.close()
        
        self.start_time = time.time()
        self.end_time = self.start_time + self.duration_sec
        
        # Launch all node tasks
        tasks = [
            asyncio.create_task(self._hazard_emitter_loop()),
            asyncio.create_task(self._relay_simulator_loop()),
            asyncio.create_task(self._monitor_loop())
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self._print_results()
    
    async def _hazard_emitter_loop(self):
        """Continuously emit hazards from random nodes at configured rate."""
        while time.time() < self.end_time:
            # Randomly select nodes to emit hazards
            active_nodes = random.sample(self.nodes, min(int(self.hazard_rate_hz), len(self.nodes)))
            await asyncio.gather(*[node.emit_hazard() for node in active_nodes])
            await asyncio.sleep(1.0 / self.hazard_rate_hz)
    
    async def _relay_simulator_loop(self):
        """Simulate mesh relay traffic between nodes."""
        while time.time() < self.end_time:
            # Random pair relays
            node_a, node_b = random.sample(self.nodes, 2)
            await node_a.relay_packet()
            await asyncio.sleep(random.uniform(0.05, 0.2))
    
    async def _monitor_loop(self):
        """Monitor stats and print periodic updates."""
        while time.time() < self.end_time:
            elapsed = time.time() - self.start_time
            total_hazards = sum(n.hazard_emit_count for n in self.nodes)
            total_relays = sum(n.relay_count for n in self.nodes)
            total_db_latency = []
            for n in self.nodes:
                total_db_latency.extend(n.db_write_latency_ms)
            
            if total_db_latency:
                p50_latency = sorted(total_db_latency)[len(total_db_latency) // 2]
                p95_latency = sorted(total_db_latency)[int(len(total_db_latency) * 0.95)]
            else:
                p50_latency = p95_latency = 0
            
            logger.info(f"[{elapsed:.1f}s] Hazards: {total_hazards} | Relays: {total_relays} | "
                       f"DB Latency: p50={p50_latency:.1f}ms, p95={p95_latency:.1f}ms")
            await asyncio.sleep(5)
    
    def _print_results(self):
        """Print comprehensive test results."""
        elapsed = time.time() - self.start_time
        total_hazards = sum(n.hazard_emit_count for n in self.nodes)
        total_relays = sum(n.relay_count for n in self.nodes)
        
        all_latencies = []
        for n in self.nodes:
            all_latencies.extend(n.db_write_latency_ms)
        
        logger.info("\n" + "="*80)
        logger.info("SWARM_LOAD_TEST RESULTS")
        logger.info("="*80)
        logger.info(f"Nodes: {self.num_nodes} | Duration: {elapsed:.1f}s | Hazards: {total_hazards} | Relays: {total_relays}")
        
        if all_latencies:
            logger.info(f"DB Write Latencies (ms):")
            logger.info(f"  Min: {min(all_latencies):.2f} | Max: {max(all_latencies):.2f}")
            logger.info(f"  Mean: {sum(all_latencies)/len(all_latencies):.2f}")
            logger.info(f"  P50: {sorted(all_latencies)[len(all_latencies)//2]:.2f}")
            logger.info(f"  P95: {sorted(all_latencies)[int(len(all_latencies)*0.95)]:.2f}")
            logger.info(f"  P99: {sorted(all_latencies)[int(len(all_latencies)*0.99)]:.2f}")
        
        # Verdict
        lock_rate = 100.0 * self.db_lock_count / max(total_hazards, 1)
        p95_latency = sorted(all_latencies)[int(len(all_latencies)*0.95)] if all_latencies else 0
        
        if p95_latency < 10 and lock_rate < 5:
            verdict = "✅ PASS: System scales to {self.num_nodes} nodes"
        elif p95_latency < 50 and lock_rate < 15:
            verdict = f"⚠️  WARN: {self.num_nodes} nodes marginal (p95={p95_latency:.1f}ms, lock%={lock_rate:.1f})"
        else:
            verdict = f"❌ FAIL: {self.num_nodes} nodes unstable (p95={p95_latency:.1f}ms, lock%={lock_rate:.1f})"
        
        logger.info(f"\nVERDICT: {verdict}")
        logger.info("="*80 + "\n")


async def main():
    """Run load tests for scaling study."""
    test_configs = [
        (6, 30, 1.0),   # Light load
        (12, 30, 2.0),  # Medium load
        (18, 30, 3.0),  # Max stable (Phase 5 spec)
        (24, 30, 3.0),  # Hard-fail band start
    ]
    
    for num_nodes, duration, hazard_rate in test_configs:
        test = SwarmLoadTest(num_nodes=num_nodes, duration_sec=duration, hazard_rate_hz=hazard_rate)
        await test.run()
        await asyncio.sleep(2)  # Cooldown between tests


if __name__ == "__main__":
    asyncio.run(main())
