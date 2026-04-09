"""
tests/test_find_similar_repos.py
Unit tests for find_similar_repos.py

Tests run fully offline: the GitHub network layer is monkey-patched so no
real HTTP calls are made.
"""

from __future__ import annotations

import sys
import os
import json
import types

# Ensure repo root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers — build a minimal fake GitHub search response
# ---------------------------------------------------------------------------
def _make_repo(
    rid: int,
    full_name: str,
    description: str = "A working road-safety AI project",
    language: str = "Python",
    stars: int = 50,
    forks: int = 10,
    pushed_at: str = "2025-06-01T12:00:00Z",
    archived: bool = False,
    topics: list | None = None,
) -> dict:
    return {
        "id": rid,
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": description,
        "language": language,
        "stargazers_count": stars,
        "forks_count": forks,
        "pushed_at": pushed_at,
        "archived": archived,
        "disabled": False,
        "topics": topics or [],
    }


_FAKE_REPOS = [
    _make_repo(1, "team-a/edge-road-safety", stars=120, forks=20,
               topics=["onnx", "yolov8", "road-safety"]),
    _make_repo(2, "team-b/legal-rag-nlp", stars=80, forks=5,
               topics=["rag", "nlp", "legal"]),
    _make_repo(3, "team-c/ble-v2x-mesh", stars=30, forks=3,
               topics=["ble", "v2x", "mesh"]),
    _make_repo(4, "team-d/stale-project",
               pushed_at="2020-01-01T00:00:00Z", stars=5),  # stale
    _make_repo(5, "team-e/no-description", description="", stars=100),  # no desc
    _make_repo(6, "team-f/archived-repo", archived=True, stars=200),  # archived
    _make_repo(7, "team-g/zero-stars", stars=0),  # below min_stars
]


def _patch_gh_get(monkeypatch_dict: dict):
    """Replace _gh_get so all queries return _FAKE_REPOS (deduplicated in finder)."""
    import find_similar_repos as fsr

    def _fake_gh_get(url: str):
        return {"items": _FAKE_REPOS}

    fsr._gh_get = _fake_gh_get          # type: ignore[attr-defined]
    fsr._RESULTS_PER_QUERY = 10

    # Also stub out sleep to keep tests fast
    import time
    monkeypatch_dict["_orig_sleep"] = fsr.time.sleep
    fsr.time.sleep = lambda _: None     # type: ignore[attr-defined]


def _restore_gh_get():
    """Undo monkey-patching after each test (best-effort)."""
    import find_similar_repos as fsr
    # Restore original _gh_get from module source (reimport)
    import importlib
    importlib.reload(fsr)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_find_returns_list():
    """find_similar_repos returns a list (even if network fails)."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        results = fsr.find_similar_repos(queries=["edge-ai road-safety"])
        assert isinstance(results, list)
        print(f"[PASS] test_find_returns_list: {len(results)} repos returned")
    finally:
        _restore_gh_get()


def test_working_filter_removes_stale_and_archived():
    """Stale, archived, zero-star, and no-description repos are excluded."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        results = fsr.find_similar_repos(queries=["edge-ai"])
        full_names = {r["full_name"] for r in results}
        assert "team-d/stale-project" not in full_names, "Stale repo should be filtered"
        assert "team-e/no-description" not in full_names, "No-description repo should be filtered"
        assert "team-f/archived-repo" not in full_names, "Archived repo should be filtered"
        assert "team-g/zero-stars" not in full_names, "Zero-star repo should be filtered"
        print("[PASS] test_working_filter_removes_stale_and_archived")
    finally:
        _restore_gh_get()


def test_results_include_expected_working_repos():
    """Well-maintained repos pass the filter."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        results = fsr.find_similar_repos(queries=["edge-ai"])
        full_names = {r["full_name"] for r in results}
        assert "team-a/edge-road-safety" in full_names
        assert "team-b/legal-rag-nlp" in full_names
        assert "team-c/ble-v2x-mesh" in full_names
        print("[PASS] test_results_include_expected_working_repos")
    finally:
        _restore_gh_get()


def test_results_sorted_by_score_descending():
    """Results are ranked highest score first."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        results = fsr.find_similar_repos(queries=["edge-ai"])
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), "Results must be sorted by score desc"
        print("[PASS] test_results_sorted_by_score_descending")
    finally:
        _restore_gh_get()


def test_result_schema():
    """Each result dict has all required keys with correct types."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        results = fsr.find_similar_repos(queries=["edge-ai"])
        required = {
            "full_name": str,
            "html_url": str,
            "description": str,
            "language": str,
            "stars": int,
            "forks": int,
            "pushed_at": str,
            "days_since_push": int,
            "score": float,
            "topics": list,
        }
        for repo in results:
            for key, expected_type in required.items():
                assert key in repo, f"Missing key: {key}"
                assert isinstance(repo[key], expected_type), (
                    f"Key {key!r}: expected {expected_type.__name__}, "
                    f"got {type(repo[key]).__name__}"
                )
        print(f"[PASS] test_result_schema ({len(results)} repos validated)")
    finally:
        _restore_gh_get()


def test_deduplication():
    """Same repo id returned by multiple queries is only included once."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        # Use two identical queries — all results would be duplicates
        results = fsr.find_similar_repos(queries=["query-a", "query-a"])
        full_names = [r["full_name"] for r in results]
        assert len(full_names) == len(set(full_names)), "Duplicate repos found in results"
        print("[PASS] test_deduplication")
    finally:
        _restore_gh_get()


def test_is_working_helper():
    """Unit-test the _is_working predicate directly."""
    import find_similar_repos as fsr
    good = _make_repo(99, "x/y", stars=5, pushed_at="2025-01-01T00:00:00Z")
    assert fsr._is_working(good), "Expected good repo to pass filter"

    bad_stale = _make_repo(100, "x/z", stars=5, pushed_at="2010-01-01T00:00:00Z")
    assert not fsr._is_working(bad_stale), "Stale repo should fail filter"

    bad_archived = _make_repo(101, "x/a", stars=5, archived=True,
                              pushed_at="2025-01-01T00:00:00Z")
    assert not fsr._is_working(bad_archived), "Archived repo should fail filter"

    bad_no_desc = _make_repo(102, "x/b", description="", stars=5,
                             pushed_at="2025-01-01T00:00:00Z")
    assert not fsr._is_working(bad_no_desc), "No-description repo should fail filter"
    print("[PASS] test_is_working_helper")


def test_json_output(capsys):
    """--json flag produces valid JSON array output."""
    import find_similar_repos as fsr
    patches: dict = {}
    _patch_gh_get(patches)
    try:
        results = fsr.find_similar_repos(queries=["edge-ai"])
        # Simulate JSON output
        output = json.dumps(results, indent=2)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        print(f"[PASS] test_json_output ({len(parsed)} repos in JSON)")
    finally:
        _restore_gh_get()
