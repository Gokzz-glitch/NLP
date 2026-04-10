from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    status: str
    evidence: str
    note: str = ""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def run_checks() -> List[CheckResult]:
    results: List[CheckResult] = []

    # Core artifact presence
    core_files = [
        "agent2_dashboard/api.py",
        "core/payment_gateway.py",
        "etl/spatial_database_init.py",
        "scripts/realworld_ssl_goal_loop.py",
    ]
    missing = [f for f in core_files if not _exists(f)]
    results.append(
        CheckResult(
            "Core implementation files present",
            "PASS" if not missing else "FAIL",
            ", ".join(core_files),
            "Missing: " + ", ".join(missing) if missing else "",
        )
    )

    # Submission package presence
    package_files = [
        "README_SAASATHON.md",
        "SAASATHON_SUBMISSION.md",
        "DEMO_GUIDE.md",
        "LANDING_PAGE.html",
        "JURY_SUBMISSION_FORM.md",
        "SUBMISSION_PACKAGE_INDEX.md",
    ]
    missing_pkg = [f for f in package_files if not _exists(f)]
    results.append(
        CheckResult(
            "Submission package files present",
            "PASS" if not missing_pkg else "FAIL",
            ", ".join(package_files),
            "Missing: " + ", ".join(missing_pkg) if missing_pkg else "",
        )
    )

    # Evidence files
    evidence_files = [
        "logs/ssl_verify_20260407_132828.log",
        "Testing videos/ssl_verification_results/verification_report.json",
    ]
    missing_ev = [f for f in evidence_files if not _exists(f)]
    results.append(
        CheckResult(
            "Runtime evidence files present",
            "PASS" if not missing_ev else "FAIL",
            ", ".join(evidence_files),
            "Missing: " + ", ".join(missing_ev) if missing_ev else "",
        )
    )

    # Jury form placeholder scan
    jury = _read(ROOT / "JURY_SUBMISSION_FORM.md") if _exists("JURY_SUBMISSION_FORM.md") else ""
    placeholder_hits = re.findall(r"\[(?:TODO|Your Name|Team Member|Founder LinkedIn|Member 2 LinkedIn|Member 3 LinkedIn)[^\]]*\]", jury)
    example_hits = re.findall(r"example\.com", jury, flags=re.IGNORECASE)
    results.append(
        CheckResult(
            "Jury form placeholder/example-domain scan",
            "PASS" if not placeholder_hits and not example_hits else "FAIL",
            "JURY_SUBMISSION_FORM.md",
            f"placeholders={len(placeholder_hits)}, example_domains={len(example_hits)}",
        )
    )

    # Demo video link sanity
    demo_link_line = ""
    for line in jury.splitlines():
        if line.strip().startswith("**Video Link:**"):
            demo_link_line = line.strip()
            break
    video_is_repo_doc = "github.com" in demo_link_line and "DEMO_GUIDE.md" in demo_link_line
    results.append(
        CheckResult(
            "Demo video criterion link",
            "PARTIAL" if video_is_repo_doc else ("PASS" if demo_link_line else "FAIL"),
            demo_link_line or "(not found)",
            "A real hosted video URL is required for full pass.",
        )
    )

    # Public deployment URL sanity (localhost is not public)
    live_url_block = ""
    in_urls = False
    for line in jury.splitlines():
        if line.strip() == "**Live Deployment URLs:**":
            in_urls = True
            continue
        if in_urls and line.strip().startswith("```"):
            continue
        if in_urls and line.strip() == "---":
            in_urls = False
        if in_urls:
            live_url_block += line + "\n"
    uses_localhost = "localhost" in live_url_block.lower()
    results.append(
        CheckResult(
            "Live deployment URL criterion",
            "PARTIAL" if uses_localhost else "PASS",
            live_url_block.strip() or "(not found)",
            "Public reachable URLs are required for final submission.",
        )
    )

    return results


def main() -> None:
    results = run_checks()
    summary = {
        "pass": sum(1 for r in results if r.status == "PASS"),
        "partial": sum(1 for r in results if r.status == "PARTIAL"),
        "fail": sum(1 for r in results if r.status == "FAIL"),
        "total": len(results),
    }
    payload = {
        "summary": summary,
        "results": [r.__dict__ for r in results],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
