#!/usr/bin/env python3
"""
Stress test G0DM0D3 with aggressive project-improvement questions.

Purpose:
- Ask a large, structured set of hard improvement questions.
- Capture model answers for architecture, reliability, security, ML quality, and ops.
- Produce a consolidated JSON report for review.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.godmod3_research import check_connection, run_research_query


def _question_bank() -> List[str]:
    return [
        "What are the top 10 architectural risks in this road-safety/SSL pipeline and exact mitigation steps?",
        "Which parts of the current data pipeline can silently corrupt labels, and how would you detect/prevent that?",
        "How should we redesign the SSL verification loop to maximize precision at high speed (>100 km/h)?",
        "What should be the strict acceptance gates before promoting a new model to production?",
        "Where can data leakage happen between train/val/test in this repository, and what controls should be enforced?",
        "What anti-regression test matrix is missing for the end-to-end realworld SSL loop?",
        "How would you harden the process model to prevent duplicate loop instances and zombie processes?",
        "What are the highest ROI latency optimizations across video decode, YOLO inference, and verifier calls?",
        "How should we build a robust fallback strategy when verifier API quota is exhausted?",
        "What observability signals are missing to debug false negatives in night/rain conditions?",
        "How can we improve hard-negative mining without poisoning the training distribution?",
        "What schema changes should be made for logs to support forensic replay and auditability?",
        "How do we improve token/secret handling so API keys never leak to logs or artifacts?",
        "What are the security vulnerabilities likely in this codebase and concrete patch-level fixes?",
        "How should we benchmark model drift week-over-week with minimal manual overhead?",
        "What deployment strategy reduces outage risk when updating loop scripts and models?",
        "How can we make the training loop more deterministic and reproducible across machines?",
        "What improvements are needed in dataset balancing for rare hazards and edge cases?",
        "How should we evaluate verifier disagreement cases to improve both model and verifier policy?",
        "What governance and rollback playbook should be mandatory for this project?",
    ]


def _default_mode() -> str:
    mode = os.getenv("GODMODE_RESEARCH_MODE", "classic").strip().lower()
    return mode if mode in {"classic", "ultraplinian"} else "classic"


def _default_model(mode: str) -> str:
    if mode == "classic":
        return os.getenv("GODMODE_CLASSIC_MODEL", "openai/gpt-4o").strip()
    return os.getenv("GODMODE_MODEL", "ultraplinian/fast").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Stress-test G0DM0D3 with project-improvement questions")
    parser.add_argument("--base-url", default=os.getenv("GODMODE_BASE_URL", "http://127.0.0.1:7860"))
    parser.add_argument("--mode", choices=["classic", "ultraplinian"], default=_default_mode())
    parser.add_argument("--model", default="", help="Override model; default depends on mode")
    parser.add_argument("--max-questions", type=int, default=20)
    parser.add_argument("--sleep-sec", type=float, default=0.4)
    parser.add_argument("--save-dir", default="logs/research")
    args = parser.parse_args()

    godmode_key = os.getenv("GODMODE_API_KEY") or os.getenv("GODMODE_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not godmode_key:
        raise SystemExit("Missing GODMODE_API_KEY/GODMODE_KEY")

    model = args.model.strip() or _default_model(args.mode)

    ok, details = check_connection(args.base_url.rstrip("/"), godmode_key)
    if not ok:
        raise SystemExit(f"Connection check failed: {details}")

    questions = _question_bank()[: max(1, int(args.max_questions))]
    out_dir = PROJECT_ROOT / args.save_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    report: Dict[str, object] = {
        "started_at": datetime.now().isoformat(),
        "mode": args.mode,
        "model": model,
        "base_url": args.base_url,
        "question_count": len(questions),
        "results": [],
    }

    print(f"Running stress review: {len(questions)} questions | mode={args.mode} | model={model}")

    for idx, q in enumerate(questions, start=1):
        status, result = run_research_query(
            base_url=args.base_url.rstrip("/"),
            godmode_key=godmode_key,
            openrouter_key=openrouter_key,
            model=model,
            query=q,
        )
        answer = ""
        if isinstance(result, dict):
            answer = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

        report["results"].append(
            {
                "index": idx,
                "question": q,
                "status": status,
                "answer": answer,
                "raw": result,
            }
        )

        verdict = "OK" if status == 200 else "FAIL"
        print(f"[{idx:02d}/{len(questions)}] {verdict} status={status}")
        if args.sleep_sec > 0:
            time.sleep(args.sleep_sec)

    report["ended_at"] = datetime.now().isoformat()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"godmod3_project_improvement_stress_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    passed = sum(1 for r in report["results"] if r.get("status") == 200)
    print(f"Completed: {passed}/{len(questions)} successful. Report: {out_path}")


if __name__ == "__main__":
    main()
