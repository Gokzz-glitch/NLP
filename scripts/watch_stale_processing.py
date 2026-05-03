#!/usr/bin/env python3
"""Watchdog for stale ETL processing files."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def find_stale(processing_dir: Path, stale_seconds: int):
    now = time.time()
    rows = []
    for p in sorted(processing_dir.glob("*.pdf")):
        age = now - p.stat().st_mtime
        if age >= stale_seconds:
            rows.append({"file": str(p), "age_seconds": round(age, 2)})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="raw_data")
    ap.add_argument("--stale-seconds", type=int, default=3600)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    processing = Path(args.raw_dir) / "processing"
    processing.mkdir(parents=True, exist_ok=True)
    stale = find_stale(processing, args.stale_seconds)

    if args.json:
        print(json.dumps({"stale_count": len(stale), "stale": stale}, indent=2))
    else:
        print(f"stale_count={len(stale)}")
        for row in stale:
            print(f"STALE {row['age_seconds']}s {row['file']}")


if __name__ == "__main__":
    main()
