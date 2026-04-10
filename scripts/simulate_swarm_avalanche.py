import asyncio
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure ledger can boot even in isolated runtime.
os.environ.setdefault("DASHBOARD_SECRET_KEY", "SECURE_VAULT_ACTIVE")

from agents.api_bridge import APIBridgeAgent
from agents.legal_rag import LegalRAG
from core.agent_bus import bus
from core.knowledge_ledger import ledger

LOG_FILE = PROJECT_ROOT / "CRUCIBLE_AUDIT_LOG.md"
RESULT_PATH = PROJECT_ROOT / "runs" / "crucible" / "swarm_avalanche_report.json"
RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)


def append_log(section_title: str, lines: List[str]) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n## {section_title} ({ts})\n")
        for line in lines:
            f.write(f"- {line}\n")


class DummyClient:
    def __init__(self, name: str, latency_max_sec: float = 2.0, fail_prob: float = 0.02):
        self.name = name
        self.latency_max_sec = latency_max_sec
        self.fail_prob = fail_prob

    async def send(self, message: str):
        # Random network spike up to 2000ms.
        await asyncio.sleep(random.uniform(0.02, self.latency_max_sec))
        if random.random() < self.fail_prob:
            raise RuntimeError(f"{self.name}: simulated disconnect")
        return True


class HashableDummyClient(DummyClient):
    def __hash__(self):
        return hash(self.name)


def build_payload(node_id: int) -> Dict:
    base_lat = 13.045 + random.uniform(-0.00035, 0.00035)
    base_lon = 80.245 + random.uniform(-0.00035, 0.00035)
    speed_options = [20, 30, 40, 50, 60, 80, 100]

    return {
        "event_id": f"crucible-node-{node_id}-{int(time.time() * 1000)}",
        "node_id": f"BLE-NODE-{node_id:02d}",
        "hazard_type": random.choice(["POTHOLE", "COLLISION_RISK", "BLACKSPOT", "PEDESTRIAN" ]),
        "hazard_coordinates": {"lat": base_lat, "lon": base_lon},
        "conflicting_speed_limit_kmh": random.choice(speed_options),
        "origin_timestamp_ms": int(time.time() * 1000),
        "network_latency_ms": random.randint(100, 2000),
        "radius_m": random.randint(25, 100),
    }


def stress_rag_query(payload: Dict) -> float:
    rag = LegalRAG(jurisdiction="TN")
    t0 = time.perf_counter()
    vt = "SPEEDING" if payload["conflicting_speed_limit_kmh"] > 60 else "SPEED_CAMERA_UNSIGNED"
    rag.query_violation(vt, {"zone": "CITY_ARTERIAL", "speed_kmh": payload["conflicting_speed_limit_kmh"]})
    return (time.perf_counter() - t0) * 1000.0


def cycle(bridge: APIBridgeAgent, cycle_id: int, event_count: int = 50) -> Dict:
    results = {
        "cycle_id": cycle_id,
        "event_count": event_count,
        "emit_errors": 0,
        "rag_p95_ms": 0.0,
        "rag_mean_ms": 0.0,
        "bridge_p95_ms": 0.0,
        "broadcast_p95_ms": 0.0,
        "queue_depth": 0,
        "duration_sec": 0.0,
        "crashed": False,
        "tuning_actions": [],
    }

    t0 = time.perf_counter()

    payloads = [build_payload(i + 1) for i in range(event_count)]

    rag_times = []

    def emit_one(payload: Dict):
        try:
            # conflicting broadcasts + hazard telemetry
            bridge._forward_to_mobile("FAST_CRITICAL_ALERT", payload)
            bridge._forward_to_mobile("REGULATORY_CONFLICT", payload)
            bus.emit("VISION_HAZARD_DETECTED", payload)
            ledger.log_finding("CrucibleAvalanche", "swarm_event", payload)
        except Exception:
            results["emit_errors"] += 1

    try:
        with ThreadPoolExecutor(max_workers=event_count) as ex:
            futures = [ex.submit(emit_one, p) for p in payloads]
            for f in as_completed(futures):
                f.result()

        with ThreadPoolExecutor(max_workers=event_count) as ex:
            futures = [ex.submit(stress_rag_query, p) for p in payloads]
            for f in as_completed(futures):
                rag_times.append(f.result())

        # Give async bridge broadcast tasks time to finish.
        time.sleep(3.0)

        health = bridge.get_telemetry_health()
        results["bridge_p95_ms"] = float(health["bridge_latency_ms"]["p95"])
        results["broadcast_p95_ms"] = float(health["bridge_broadcast_ms"]["p95"])
        results["queue_depth"] = int(getattr(ledger, "_write_queue").qsize())

        if rag_times:
            rag_sorted = sorted(rag_times)
            idx = int(round(0.95 * (len(rag_sorted) - 1)))
            idx = max(0, min(idx, len(rag_sorted) - 1))
            results["rag_p95_ms"] = float(rag_sorted[idx])
            results["rag_mean_ms"] = float(sum(rag_times) / len(rag_times))
    except Exception as e:
        results["crashed"] = True
        results["emit_errors"] += 1
        results["tuning_actions"].append(f"cycle_exception:{e}")

    results["duration_sec"] = round(time.perf_counter() - t0, 3)
    return results


def apply_autonomous_tuning(bridge: APIBridgeAgent, cycle_result: Dict) -> List[str]:
    actions = []

    if cycle_result["queue_depth"] > 2500 or cycle_result["crashed"]:
        os.environ["LEDGER_BUSY_TIMEOUT_MS"] = "25000"
        os.environ["LEDGER_WRITE_RETRIES"] = "6"
        os.environ["LEDGER_QUEUE_PUT_TIMEOUT_SEC"] = "0.4"
        actions.append("Increased ledger busy_timeout/write retries/queue put timeout")

    if cycle_result["broadcast_p95_ms"] > 1200:
        bridge._housekeeping_every_ticks = max(10, bridge._housekeeping_every_ticks - 4)
        bridge._seen_trim_ratio = min(0.60, bridge._seen_trim_ratio + 0.10)
        bridge._pending_trim_ratio = min(0.65, bridge._pending_trim_ratio + 0.10)
        actions.append("Raised bridge cache trim aggressiveness for spike containment")

    if cycle_result["emit_errors"] > 0:
        bridge._dedup_window_ms = max(800, int(bridge._dedup_window_ms * 0.85))
        actions.append("Reduced dedup window to absorb conflicting repeats")

    if cycle_result["bridge_p95_ms"] > 900:
        bridge._broadcast_spike_ms = max(25.0, bridge._broadcast_spike_ms - 5.0)
        actions.append("Lowered broadcast spike threshold to trigger earlier downshift")

    return actions


def run_avalanche() -> int:
    random.seed(208)

    # Bridge without external socket server; we inject dummy clients to exercise async broadcast path.
    bridge = APIBridgeAgent(host="127.0.0.1", port=8765)
    bridge.start()
    time.sleep(0.2)
    bridge.clients = {HashableDummyClient(f"dummy-{i+1}") for i in range(8)}

    summary = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_events": 50,
        "cycles": [],
        "final_status": "unknown",
    }

    max_cycles = 6
    success = False

    for cycle_id in range(1, max_cycles + 1):
        cycle_result = cycle(bridge, cycle_id, event_count=50)

        # success criteria: no crash, low errors, queue not exploding
        success = (
            not cycle_result["crashed"]
            and cycle_result["emit_errors"] == 0
            and cycle_result["queue_depth"] < 3000
        )

        if not success:
            actions = apply_autonomous_tuning(bridge, cycle_result)
            cycle_result["tuning_actions"].extend(actions)

        summary["cycles"].append(cycle_result)

        if success:
            break

    summary["final_status"] = "stable" if success else "degraded"

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log_lines = [
        f"Result file: {RESULT_PATH}",
        f"Final status: {summary['final_status']}",
        f"Cycles executed: {len(summary['cycles'])}",
    ]
    for c in summary["cycles"]:
        log_lines.append(
            "Cycle {cycle}: crash={crash} emit_errors={errs} queue={queue} rag_p95_ms={rag:.2f} broadcast_p95_ms={br:.2f}".format(
                cycle=c["cycle_id"],
                crash=c["crashed"],
                errs=c["emit_errors"],
                queue=c["queue_depth"],
                rag=c["rag_p95_ms"],
                br=c["broadcast_p95_ms"],
            )
        )
        for a in c["tuning_actions"]:
            log_lines.append(f"Cycle {c['cycle_id']} tuning: {a}")

    append_log("CRUCIBLE Swarm Avalanche", log_lines)

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(run_avalanche())
