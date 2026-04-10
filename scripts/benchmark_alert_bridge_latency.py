#!/usr/bin/env python3
"""Benchmark end-to-end bus -> API bridge -> websocket client latency.

This runs fully local to measure the alert delivery path used by phone UI clients.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import List

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.api_bridge import APIBridgeAgent
from core.agent_bus import bus


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((p / 100.0) * (len(ordered) - 1)))
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


async def run_benchmark(host: str, port: int, runs: int, warmup: int, pause_ms: float) -> dict:
    uri = f"ws://{host}:{port}"
    latencies_ms: List[float] = []
    bridge_delays_ms: List[float] = []
    timeouts = 0

    async with websockets.connect(uri, max_queue=256) as ws:
        total = warmup + runs
        for i in range(total):
            now_ms = int(time.time() * 1000)
            sent_ns = time.perf_counter_ns()
            payload = {
                "type": "POTHOLE",
                "severity": "CRITICAL",
                "seq": i,
                "_event_ts_ms": now_ms,
                "_sent_perf_ns": sent_ns,
            }

            bus.emit("SENTINEL_FUSION_ALERT", payload)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                timeouts += 1
                continue
            received_ns = time.perf_counter_ns()
            msg = json.loads(raw)

            if msg.get("channel") != "SENTINEL_FUSION_ALERT":
                continue

            rx_payload = msg.get("payload", {})
            seq = rx_payload.get("seq")
            if seq != i:
                continue

            # Simulate mobile/frontend ACK at the exact local time acoustic warning fires.
            ack_payload = {
                "alert_id": rx_payload.get("alert_id"),
                "origin_timestamp_ms": rx_payload.get("origin_timestamp_ms", now_ms),
                "ack_timestamp_ms": int(time.time() * 1000),
                "source": "benchmark_client",
                "fired": True,
            }
            await ws.send(json.dumps({"channel": "ALERT_RECEIVED_ACK", "payload": ack_payload}))

            e2e_ms = (received_ns - sent_ns) / 1_000_000.0
            bridge_tx_ms = rx_payload.get("_bridge_tx_ts_ms", now_ms)
            bridge_delay_ms = float(bridge_tx_ms - now_ms)

            if i >= warmup:
                latencies_ms.append(e2e_ms)
                bridge_delays_ms.append(bridge_delay_ms)

            if pause_ms > 0:
                await asyncio.sleep(pause_ms / 1000.0)

    return {
        "runs": len(latencies_ms),
        "mean_ms": statistics.mean(latencies_ms) if latencies_ms else 0.0,
        "p50_ms": percentile(latencies_ms, 50),
        "p95_ms": percentile(latencies_ms, 95),
        "p99_ms": percentile(latencies_ms, 99),
        "min_ms": min(latencies_ms) if latencies_ms else 0.0,
        "max_ms": max(latencies_ms) if latencies_ms else 0.0,
        "bridge_delay_mean_ms": statistics.mean(bridge_delays_ms) if bridge_delays_ms else 0.0,
        "timeouts": timeouts,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark bus->bridge websocket alert latency")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9876)
    p.add_argument("--runs", type=int, default=200)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--pause-ms", type=float, default=1.0)
    return p.parse_args()


async def amain() -> int:
    args = parse_args()

    bridge = APIBridgeAgent(host=args.host, port=args.port)
    bridge.start()

    # Give server thread a moment to bind before connecting.
    await asyncio.sleep(0.3)

    stats = await run_benchmark(
        host=args.host,
        port=args.port,
        runs=max(1, args.runs),
        warmup=max(0, args.warmup),
        pause_ms=max(0.0, args.pause_ms),
    )

    await asyncio.sleep(0.2)
    telemetry = bridge.get_telemetry_health()
    stats["roundtrip_ms_from_ack"] = telemetry.get("e2e_roundtrip_ms", {})

    print("ALERT_BRIDGE_BENCH")
    print(json.dumps(stats, indent=2))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
