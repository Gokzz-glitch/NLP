"""
find_similar_repos.py
SmartSalai Edge-Sentinel — GitHub Similar-Repository Finder

Searches GitHub for publicly available repositories that are similar to this
project in terms of technology stack and domain, then filters for "working"
projects (recently pushed, has stars, non-empty description).

Usage:
    python find_similar_repos.py            # print ranked table
    python find_similar_repos.py --json     # machine-readable JSON output

No GitHub token required for basic use (60 req/h unauthenticated).
Set the env-var GITHUB_TOKEN to raise the limit to 5 000 req/h.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_sentinel.find_similar_repos")

# ---------------------------------------------------------------------------
# Search queries — each string targets a different facet of the project
# ---------------------------------------------------------------------------
_SEARCH_QUERIES: List[str] = [
    # Edge AI / on-device inference
    "edge-ai onnx road-safety python",
    # Retrieval-Augmented Generation, legal
    "rag legal nlp python edge",
    # Multi-agent + vehicle safety
    "multi-agent road-safety python",
    # Vision + traffic sign detection
    "yolov8 traffic-sign detection python",
    # BLE V2X / vehicular mesh
    "ble v2x mesh python raspberry-pi",
    # TCN sensor fusion
    "tcn sensor-fusion imu near-miss",
    # iRAD / road-accident database
    "irad accident-data road-safety india",
]

_GITHUB_API = "https://api.github.com"
_RESULTS_PER_QUERY = 10          # keep top-N per query to limit API calls
_MIN_STARS = 1                   # drop abandoned / placeholder repos
_STALE_DAYS = 730                # drop repos with no push in last N days


# ---------------------------------------------------------------------------
# GitHub REST API helpers
# ---------------------------------------------------------------------------
def _gh_headers() -> Dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "")
    headers: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SmartSalai-Edge-Sentinel-RepoFinder/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gh_get(url: str) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers=_gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        logger.warning("GitHub API error %s for %s", exc.code, url)
        return None
    except Exception as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return None


def _search_repos(query: str, per_page: int = _RESULTS_PER_QUERY) -> List[Dict[str, Any]]:
    params = urllib.parse.urlencode({
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    url = f"{_GITHUB_API}/search/repositories?{params}"
    data = _gh_get(url)
    if data is None:
        return []
    return data.get("items", [])


# ---------------------------------------------------------------------------
# Filtering & scoring
# ---------------------------------------------------------------------------
def _days_since(iso_str: Optional[str]) -> float:
    """Return days since an ISO-8601 timestamp, or infinity if unparseable."""
    if not iso_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(iso_str.rstrip("Z")).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return float("inf")


def _is_working(repo: Dict[str, Any]) -> bool:
    """Return True if the repo looks actively maintained."""
    if repo.get("stargazers_count", 0) < _MIN_STARS:
        return False
    if repo.get("archived") or repo.get("disabled"):
        return False
    if _days_since(repo.get("pushed_at")) > _STALE_DAYS:
        return False
    if not repo.get("description", "").strip():
        return False
    return True


def _score(repo: Dict[str, Any]) -> float:
    """Higher is more relevant / healthier."""
    stars   = repo.get("stargazers_count", 0)
    forks   = repo.get("forks_count", 0)
    freshness = max(0, _STALE_DAYS - _days_since(repo.get("pushed_at")))
    return stars * 2 + forks + freshness * 0.1


# ---------------------------------------------------------------------------
# Main finder
# ---------------------------------------------------------------------------
def find_similar_repos(
    queries: Optional[List[str]] = None,
    min_stars: int = _MIN_STARS,
    stale_days: int = _STALE_DAYS,
    per_query: int = _RESULTS_PER_QUERY,
) -> List[Dict[str, Any]]:
    """
    Search GitHub and return a deduplicated, ranked list of repos similar to
    SmartSalai Edge-Sentinel.

    Returns a list of dicts with keys:
        full_name, html_url, description, language, stars, forks,
        pushed_at, days_since_push, score, topics
    """
    global _MIN_STARS, _STALE_DAYS
    _MIN_STARS = min_stars
    _STALE_DAYS = stale_days

    seen_ids: set = set()
    candidates: List[Dict[str, Any]] = []

    for query in (queries or _SEARCH_QUERIES):
        logger.info("Querying GitHub: %r", query)
        raw = _search_repos(query, per_page=per_query)
        for repo in raw:
            rid = repo.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            if not _is_working(repo):
                continue
            days = _days_since(repo.get("pushed_at"))
            candidates.append({
                "full_name":      repo.get("full_name", ""),
                "html_url":       repo.get("html_url", ""),
                "description":    (repo.get("description") or "").strip(),
                "language":       repo.get("language") or "—",
                "stars":          repo.get("stargazers_count", 0),
                "forks":          repo.get("forks_count", 0),
                "pushed_at":      repo.get("pushed_at", ""),
                "days_since_push": int(days),
                "score":          round(_score(repo), 1),
                "topics":         repo.get("topics", []),
            })
        # Respect secondary rate limit (GitHub allows ~10 search req/min unauth)
        time.sleep(0.7)

    candidates.sort(key=lambda r: r["score"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# CLI output
# ---------------------------------------------------------------------------
def _print_table(repos: List[Dict[str, Any]]) -> None:
    if not repos:
        print("No similar working repos found (check network / GitHub rate limits).")
        return

    col_widths = (4, 42, 52, 12, 6, 5, 15)
    header = (
        f"{'#':<{col_widths[0]}} "
        f"{'Repository':<{col_widths[1]}} "
        f"{'Description':<{col_widths[2]}} "
        f"{'Language':<{col_widths[3]}} "
        f"{'Stars':>{col_widths[4]}} "
        f"{'Forks':>{col_widths[5]}} "
        f"{'Last Push (d)':>{col_widths[6]}}"
    )
    sep = "-" * len(header)
    print("\n=== SmartSalai Edge-Sentinel — Similar Working Repositories ===\n")
    print(header)
    print(sep)
    for rank, repo in enumerate(repos, 1):
        desc = repo["description"]
        if len(desc) > col_widths[2] - 2:
            desc = desc[: col_widths[2] - 5] + "..."
        name = repo["full_name"]
        if len(name) > col_widths[1] - 2:
            name = name[: col_widths[1] - 5] + "..."
        print(
            f"{rank:<{col_widths[0]}} "
            f"{name:<{col_widths[1]}} "
            f"{desc:<{col_widths[2]}} "
            f"{repo['language']:<{col_widths[3]}} "
            f"{repo['stars']:>{col_widths[4]}} "
            f"{repo['forks']:>{col_widths[5]}} "
            f"{repo['days_since_push']:>{col_widths[6]}}"
        )
        print(f"     URL: {repo['html_url']}")
        if repo["topics"]:
            print(f"     Topics: {', '.join(repo['topics'][:8])}")
        print()
    print(f"Total: {len(repos)} similar working repositories found.\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Find GitHub repos similar to SmartSalai Edge-Sentinel.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON array")
    parser.add_argument(
        "--min-stars", type=int, default=_MIN_STARS,
        help=f"Minimum star count (default: {_MIN_STARS})",
    )
    parser.add_argument(
        "--stale-days", type=int, default=_STALE_DAYS,
        help=f"Max days since last push (default: {_STALE_DAYS})",
    )
    parser.add_argument(
        "--per-query", type=int, default=_RESULTS_PER_QUERY,
        help=f"Results per search query (default: {_RESULTS_PER_QUERY})",
    )
    args = parser.parse_args()

    repos = find_similar_repos(
        min_stars=args.min_stars,
        stale_days=args.stale_days,
        per_query=args.per_query,
    )

    if args.json:
        print(json.dumps(repos, indent=2))
    else:
        _print_table(repos)


if __name__ == "__main__":
    main()
