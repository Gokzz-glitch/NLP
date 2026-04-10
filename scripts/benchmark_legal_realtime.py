#!/usr/bin/env python3
"""Benchmark legal realtime paths for latency and grounding quality.

Runs three paths:
1) LegalRAG query_violation
2) create_legal_alert payload construction
3) ViolationLegalPipeline end-to-end processing

Outputs both console summary and JSON report under logs/benchmarks.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.legal_rag import LegalRAG, create_legal_alert
from scripts.violation_legal_pipeline import ViolationLegalPipeline


@dataclass
class BenchStats:
    count: int
    timeout_ms: float
    timeout_rate: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    grounding_score: float


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def score_legal_result(result: Dict, expected_section: str | None = None) -> float:
    checks = []
    checks.append(bool(result.get("relevant_sections")))
    checks.append(bool((result.get("summary") or "").strip()))
    checks.append(bool(result.get("legal_aid_contact")))

    penalties = result.get("penalty_details") or {}
    has_non_negative_penalty = True
    for detail in penalties.values():
        min_inr = detail.get("min_inr", 0)
        max_inr = detail.get("max_inr", 0)
        if min_inr < 0 or max_inr < 0 or max_inr < min_inr:
            has_non_negative_penalty = False
            break
    checks.append(has_non_negative_penalty)

    if expected_section:
        checks.append(expected_section in (result.get("relevant_sections") or []))
    else:
        checks.append(True)

    return sum(1.0 for c in checks if c) / float(len(checks))


def score_alert_payload(payload: Dict, expected_section: str | None = None) -> float:
    checks = []
    checks.append(bool(payload.get("alert_id") is not None))
    checks.append(bool(payload.get("violation_type")))
    checks.append(bool(payload.get("legal_sections")))
    checks.append(bool((payload.get("tts_script") or "").strip()))
    if expected_section:
        checks.append(expected_section in (payload.get("legal_sections") or []))
    else:
        checks.append(True)
    return sum(1.0 for c in checks if c) / float(len(checks))


def summarize(latencies_ms: List[float], timeout_ms: float, grounding_scores: List[float]) -> BenchStats:
    n = len(latencies_ms)
    timeout_count = sum(1 for x in latencies_ms if x > timeout_ms)
    return BenchStats(
        count=n,
        timeout_ms=timeout_ms,
        timeout_rate=(timeout_count / n) if n else 0.0,
        mean_ms=statistics.mean(latencies_ms) if n else 0.0,
        p50_ms=percentile(latencies_ms, 50),
        p95_ms=percentile(latencies_ms, 95),
        p99_ms=percentile(latencies_ms, 99),
        min_ms=min(latencies_ms) if n else 0.0,
        max_ms=max(latencies_ms) if n else 0.0,
        grounding_score=statistics.mean(grounding_scores) if grounding_scores else 0.0,
    )


def bench_query(rag: LegalRAG, runs: int, timeout_ms: float) -> BenchStats:
    latencies: List[float] = []
    scores: List[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        result = rag.query_violation("SPEEDING", {"zone": "HIGHWAY_NATIONAL", "speed_kmh": 95}).to_dict()
        elapsed = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed)
        scores.append(score_legal_result(result, expected_section="183"))
    return summarize(latencies, timeout_ms=timeout_ms, grounding_scores=scores)


def bench_alert(rag: LegalRAG, runs: int, timeout_ms: float) -> BenchStats:
    latencies: List[float] = []
    scores: List[float] = []
    event = {
        "event_id": "bench-evt",
        "severity": "WARNING",
        "violation_type": "SPEEDING",
        "location": {"zone": "HIGHWAY_NATIONAL", "speed_kmh": 95},
    }
    for _ in range(runs):
        start = time.perf_counter()
        payload = create_legal_alert(event, rag)
        elapsed = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed)
        scores.append(score_alert_payload(payload, expected_section="183"))
    return summarize(latencies, timeout_ms=timeout_ms, grounding_scores=scores)


def bench_pipeline(pipeline: ViolationLegalPipeline, runs: int, timeout_ms: float) -> BenchStats:
    latencies: List[float] = []
    # Pipeline does not return payload; score based on expected legal query viability in the same flow.
    scores: List[float] = []
    sink = io.StringIO()
    context = {"lat": 13.08, "lng": 80.27, "zone": "HIGHWAY_NATIONAL", "speed_kmh": 95}
    for _ in range(runs):
        start = time.perf_counter()
        with contextlib.redirect_stdout(sink):
            pipeline.process_detection("SPEEDING", 0.88, context)
        elapsed = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed)

        legal_result = pipeline.legal_rag.query_violation("SPEEDING", context).to_dict()
        scores.append(score_legal_result(legal_result, expected_section="183"))
    return summarize(latencies, timeout_ms=timeout_ms, grounding_scores=scores)


def build_report(runs: int, timeout_ms: float) -> Dict:
    rag = LegalRAG("TN")
    pipeline = ViolationLegalPipeline()

    query_stats = bench_query(rag=rag, runs=runs, timeout_ms=timeout_ms)
    alert_stats = bench_alert(rag=rag, runs=runs, timeout_ms=timeout_ms)
    pipeline_stats = bench_pipeline(pipeline=pipeline, runs=runs, timeout_ms=timeout_ms)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "runs": runs,
        "timeout_ms": timeout_ms,
        "paths": {
            "legal_query": asdict(query_stats),
            "legal_alert_payload": asdict(alert_stats),
            "violation_pipeline_e2e": asdict(pipeline_stats),
        },
    }


def print_summary(report: Dict) -> None:
    print("Legal Real-Time Benchmark")
    print("=" * 60)
    print(f"runs={report['runs']} timeout_ms={report['timeout_ms']}")
    for name, stats in report["paths"].items():
        print("-" * 60)
        print(name)
        print(
            "count={count} mean={mean_ms:.4f}ms p50={p50_ms:.4f}ms p95={p95_ms:.4f}ms "
            "p99={p99_ms:.4f}ms timeout_rate={timeout_rate:.4f} grounding={grounding_score:.4f}".format(**stats)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark legal real-time latency and grounding")
    parser.add_argument("--runs", type=int, default=500, help="Number of iterations per path")
    parser.add_argument("--timeout-ms", type=float, default=50.0, help="Latency timeout threshold per operation")
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Optional JSON output file path. Defaults to logs/benchmarks/legal_realtime_*.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(runs=max(1, args.runs), timeout_ms=max(0.1, args.timeout_ms))

    out_path = Path(args.out) if args.out else Path("logs") / "benchmarks" / f"legal_realtime_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print_summary(report)
    print("-" * 60)
    print(f"saved={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
