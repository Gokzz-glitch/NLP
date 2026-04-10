#!/usr/bin/env python3
"""Benchmark completion token throughput for local G0DM0D3 endpoint."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from statistics import mean, median
from typing import Any, Dict, List
from urllib import error, request


def _http_json(method: str, url: str, payload: Dict[str, Any] | None, headers: Dict[str, str], timeout: int = 90) -> Dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return {
                "status": int(getattr(resp, "status", 0)),
                "json": json.loads(body) if body else {},
                "raw": body,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return {
            "status": int(exc.code),
            "json": json.loads(body) if body.strip().startswith("{") else {"error": body},
            "raw": body,
        }


def _pick_model(base_url: str, auth_headers: Dict[str, str], fallback_model: str) -> str:
    res = _http_json("GET", f"{base_url}/v1/models", None, auth_headers, timeout=20)
    if res["status"] == 200:
        data = (res.get("json") or {}).get("data") or []
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and first.get("id"):
                return str(first["id"])
    return fallback_model


def _estimate_tokens_from_text(text: str) -> int:
    # Rough fallback when usage isn't provided by endpoint.
    return max(1, int(math.ceil(len(text) / 4.0)))


def main() -> int:
    p = argparse.ArgumentParser(description="Benchmark G0DM0D3 completion tokens/sec")
    p.add_argument("--base-url", default=os.getenv("GODMODE_BASE_URL", "http://127.0.0.1:7860"))
    p.add_argument("--model", default=os.getenv("GODMODE_BENCHMARK_MODEL", os.getenv("GODMODE_CLASSIC_MODEL", "openai/gpt-4o")))
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=128)
    args = p.parse_args()

    base_url = args.base_url.rstrip("/")
    godmode_key = os.getenv("GODMODE_API_KEY", "").strip() or os.getenv("GODMODE_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    auth_headers = {"Content-Type": "application/json"}
    if godmode_key:
        auth_headers["Authorization"] = f"Bearer {godmode_key}"

    model = _pick_model(base_url, auth_headers, args.model)
    if args.model.strip():
        model = args.model.strip()
    print(f"Base URL: {base_url}")
    print(f"Model: {model}")
    print(f"Runs: {args.runs}, max_tokens: {args.max_tokens}")

    rows: List[Dict[str, Any]] = []
    for i in range(args.runs):
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Write exactly 120 tokens on pothole detection reliability and end with DONE.",
                }
            ],
            "temperature": 0.2,
            "max_tokens": args.max_tokens,
        }
        if openrouter_key:
            payload["openrouter_api_key"] = openrouter_key

        t0 = time.perf_counter()
        res = _http_json("POST", f"{base_url}/v1/chat/completions", payload, auth_headers, timeout=120)
        elapsed = time.perf_counter() - t0

        status = int(res.get("status", 0))
        body = res.get("json") or {}
        message = ""
        usage = {}
        if isinstance(body, dict):
            choices = body.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = ((choices[0].get("message") or {}).get("content") or "")
            usage = body.get("usage") or {}

        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        estimated = False
        if completion_tokens is None:
            completion_tokens = _estimate_tokens_from_text(message)
            estimated = True

        tps = (float(completion_tokens) / elapsed) if elapsed > 0 else 0.0

        row = {
            "run": i + 1,
            "status": status,
            "elapsed_s": elapsed,
            "completion_tokens": int(completion_tokens),
            "tokens_per_sec": tps,
            "estimated_tokens": estimated,
            "error": (body.get("error") if isinstance(body, dict) else None),
        }
        rows.append(row)

        flag = "est" if estimated else "api"
        print(
            f"run={row['run']} status={status} elapsed={elapsed:.3f}s completion_tokens={completion_tokens} ({flag}) tps={tps:.2f}"
        )
        if status != 200:
            print(f"  error={row['error']}")

    ok = [r for r in rows if r["status"] == 200]
    if not ok:
        print("No successful runs. Endpoint may be down/auth failing.")
        return 2

    avg_tps = mean([r["tokens_per_sec"] for r in ok])
    med_tps = median([r["tokens_per_sec"] for r in ok])

    print("---")
    print(f"successful_runs={len(ok)}/{len(rows)}")
    print(f"avg_tokens_per_sec={avg_tps:.2f}")
    print(f"median_tokens_per_sec={med_tps:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
