from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "addons"
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def _exists(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _run_firecrawl_seed(query: str, limit: int, output_file: str) -> dict:
    python_exe = os.environ.get("PYTHON_EXE", "python")
    cmd = [
        python_exe,
        str(ROOT / "scripts" / "firecrawl_seed_sources.py"),
        "--query",
        query,
        "--limit",
        str(limit),
        "--output",
        output_file,
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return {
        "cmd": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def main() -> int:
    ecc_dir = ADDONS / "everything-claude-code"
    firecrawl_dir = ADDONS / "firecrawl"
    gcp_dir = ADDONS / "googlecloud-generative-ai"

    status = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "addon_presence": {
            "everything_claude_code": _exists(ecc_dir),
            "firecrawl": _exists(firecrawl_dir),
            "googlecloud_generative_ai": _exists(gcp_dir),
        },
        "firecrawl_key_present": bool(os.getenv("FIRECRAWL_API_KEY", "").strip()),
        "actions": [],
    }

    # Keep reusable research queries for repeatable SSL source refresh.
    query_file = ROOT / "config" / "addon_source_queries.txt"
    query_file.parent.mkdir(parents=True, exist_ok=True)
    queries = [
        "india pothole dashcam youtube",
        "road damage detection dashboard camera",
        "night rain road pothole footage",
    ]
    query_file.write_text("\n".join(queries) + "\n", encoding="utf-8")
    status["actions"].append(f"Wrote query presets: {query_file}")

    if status["firecrawl_key_present"] and status["addon_presence"]["firecrawl"]:
        for q in queries:
            result = _run_firecrawl_seed(
                query=q,
                limit=15,
                output_file="video_sources_youtube_runtime.txt",
            )
            status["actions"].append({"firecrawl_seed": result})
    else:
        status["actions"].append(
            "Skipped Firecrawl seeding (missing FIRECRAWL_API_KEY or firecrawl addon unavailable)."
        )

    # Emit a concise project-improvement report mapped to this codebase.
    report_md = REPORTS / f"addon_improvement_action_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
    report_md.write_text(
        "\n".join(
            [
                "# Addon Improvement Action Report",
                "",
                f"Generated: {status['timestamp']}",
                "",
                "## Addon Presence",
                f"- everything-claude-code: {status['addon_presence']['everything_claude_code']}",
                f"- firecrawl: {status['addon_presence']['firecrawl']}",
                f"- googlecloud-generative-ai: {status['addon_presence']['googlecloud_generative_ai']}",
                "",
                "## Applied Improvements",
                "- Added repeatable source discovery query presets at config/addon_source_queries.txt",
                "- Integrated optional Firecrawl auto-seeding hook via scripts/run_addon_improvements.py",
                "- Produced this runtime action report for experiment traceability",
                "",
                "## Next Loop Recommendation",
                "1. Set FIRECRAWL_API_KEY in environment.",
                "2. Run this script before each realworld SSL cycle.",
                "3. Compare precision/false-positive trend after each refresh cycle.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    status["actions"].append(f"Wrote report: {report_md}")

    status_json = REPORTS / "addon_improvement_status.json"
    status_json.write_text(json.dumps(status, indent=2), encoding="utf-8")

    print(f"Status JSON: {status_json}")
    print(f"Report: {report_md}")
    print(f"Firecrawl key present: {status['firecrawl_key_present']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
