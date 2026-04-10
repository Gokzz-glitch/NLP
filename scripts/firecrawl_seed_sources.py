from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_firecrawl_client(api_key: str):
    try:
        from firecrawl import Firecrawl
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "firecrawl-py is not installed. Install with: pip install firecrawl-py"
        ) from exc
    return Firecrawl(api_key=api_key)


def _merge_urls(existing: list[str], incoming: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in existing + incoming:
        normalized = item.strip()
        if not normalized or normalized.startswith("#"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed video source files using Firecrawl web search results."
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Search query, e.g. 'india pothole road dashcam youtube'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max search results to request.",
    )
    parser.add_argument(
        "--output",
        default="video_sources_youtube_runtime.txt",
        help="Output source-list file path.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Firecrawl API key. If omitted, FIRECRAWL_API_KEY is used.",
    )
    args = parser.parse_args()

    api_key = args.api_key.strip() or os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing Firecrawl key. Set FIRECRAWL_API_KEY or pass --api-key.")

    client = _load_firecrawl_client(api_key)
    response = client.search(args.query, limit=args.limit)

    candidates: list[str] = []
    data = []
    if isinstance(response, dict):
        data = response.get("data") or response.get("results") or []
    elif hasattr(response, "data"):
        data = getattr(response, "data") or []

    for item in data:
        url = ""
        if isinstance(item, dict):
            url = item.get("url", "")
        if url.startswith("http"):
            candidates.append(url)

    output_path = Path(args.output)
    existing = output_path.read_text(encoding="utf-8").splitlines() if output_path.exists() else []
    merged = _merge_urls(existing, candidates)

    output_path.write_text("\n".join(merged) + "\n", encoding="utf-8")

    print(f"Query: {args.query}")
    print(f"Found URLs: {len(candidates)}")
    print(f"Merged file entries: {len(merged)}")
    print(f"Updated: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
