#!/usr/bin/env python3
"""Export SmartSalai black-box telemetry for offline forensic analysis.

Artifacts included:
- Safe SQLite snapshots (knowledge ledger, spatial DB, edge RAG DB when present)
- Recent RAG/legal outputs extracted to JSON
- Current telemetry health snapshot
- Manifest with metadata and counts
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def resolve_ledger_path() -> Path:
    local_home = Path.home()
    fallback = local_home / "SmartSalai_Local" / "knowledge_ledger.db"

    try:
        from core.knowledge_ledger import DB_PATH  # Lazy import; may fail if env vars are absent.
        return Path(DB_PATH)
    except Exception:
        return fallback


def safe_sqlite_backup(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False

    src_conn = sqlite3.connect(str(src))
    src_conn.execute("PRAGMA journal_mode=WAL;")
    src_conn.execute("PRAGMA synchronous=NORMAL;")
    src_conn.execute("PRAGMA busy_timeout=5000;")
    dest_conn = sqlite3.connect(str(dest))
    dest_conn.execute("PRAGMA journal_mode=WAL;")
    dest_conn.execute("PRAGMA synchronous=NORMAL;")
    dest_conn.execute("PRAGMA busy_timeout=5000;")
    try:
        src_conn.backup(dest_conn)
        return True
    finally:
        dest_conn.close()
        src_conn.close()


def export_recent_rag_outputs(ledger_db: Path, out_json: Path, limit: int = 400) -> Dict:
    if not ledger_db.exists():
        out_json.write_text("[]", encoding="utf-8")
        return {"count": 0, "source": str(ledger_db), "status": "missing"}

    conn = sqlite3.connect(str(ledger_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")

    query = """
    SELECT id, agent_name, timestamp, finding_type, content
    FROM agent_logs
    WHERE finding_type LIKE '%LEGAL%'
       OR finding_type LIKE '%RAG%'
       OR agent_name LIKE '%RAG%'
       OR content LIKE '%section%'
       OR content LIKE '%violation%'
    ORDER BY timestamp DESC
    LIMIT ?
    """

    try:
        rows = conn.execute(query, (limit,)).fetchall()
    finally:
        conn.close()

    result: List[Dict] = []
    for row in rows:
        content_raw = row[4]
        try:
            content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except Exception:
            content = content_raw

        result.append(
            {
                "id": row[0],
                "agent_name": row[1],
                "timestamp": row[2],
                "finding_type": row[3],
                "content": content,
            }
        )

    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    return {"count": len(result), "source": str(ledger_db), "status": "ok"}


def export_recent_pothole_coordinates(spatial_db: Path, out_json: Path, limit: int = 2000) -> Dict:
    if not spatial_db.exists():
        out_json.write_text("[]", encoding="utf-8")
        return {"count": 0, "source": str(spatial_db), "status": "missing"}

    conn = sqlite3.connect(str(spatial_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")

    query = """
    SELECT id, ts, lat, lon, hazard_type, severity, source_node
    FROM ground_truth_markers
    WHERE hazard_type = 'POTHOLE' OR hazard_type LIKE '%POTHOLE%'
    ORDER BY ts DESC
    LIMIT ?
    """

    try:
        rows = conn.execute(query, (limit,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "timestamp": row["ts"],
                "lat": row["lat"],
                "lon": row["lon"],
                "hazard_type": row["hazard_type"],
                "severity": row["severity"],
                "source_node": row["source_node"],
            }
        )

    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    return {"count": len(result), "source": str(spatial_db), "status": "ok"}


def export_latency_sla_metrics(ledger_db: Path, out_json: Path, limit: int = 3000) -> Dict:
    if not ledger_db.exists():
        out_json.write_text("[]", encoding="utf-8")
        return {"count": 0, "source": str(ledger_db), "status": "missing"}

    conn = sqlite3.connect(str(ledger_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")

    query = """
    SELECT id, agent_name, timestamp, finding_type, content
    FROM agent_logs
    WHERE finding_type LIKE '%LATENCY%'
       OR content LIKE '%latency%'
       OR content LIKE '%SLA%'
       OR content LIKE '%p95%'
       OR content LIKE '%p99%'
    ORDER BY timestamp DESC
    LIMIT ?
    """

    try:
        rows = conn.execute(query, (limit,)).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        payload = row["content"]
        try:
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except Exception:
            pass
        result.append(
            {
                "id": row["id"],
                "agent_name": row["agent_name"],
                "timestamp": row["timestamp"],
                "finding_type": row["finding_type"],
                "content": payload,
            }
        )

    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    return {"count": len(result), "source": str(ledger_db), "status": "ok"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export black-box telemetry archive")
    parser.add_argument("--out-dir", default="blackbox_exports", help="Output directory for tar.gz archive")
    parser.add_argument("--rag-limit", type=int, default=400, help="Max recent RAG rows to export")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parents[1]
    out_dir = project_root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = utc_stamp()
    archive_name = f"blackbox_telemetry_{stamp}.tar.gz"
    archive_path = out_dir / archive_name

    ledger_db = resolve_ledger_path()
    spatial_db = project_root / "edge_spatial.db"
    rag_db = project_root / "edge_rag.db"
    telemetry_file = project_root / "logs" / "telemetry_health.json"

    with tempfile.TemporaryDirectory(prefix="blackbox_telemetry_") as tmp:
        stage = Path(tmp) / f"blackbox_telemetry_{stamp}"
        stage.mkdir(parents=True, exist_ok=True)

        snapshots = {}
        snapshots["knowledge_ledger"] = safe_sqlite_backup(ledger_db, stage / "knowledge_ledger.snapshot.db")
        snapshots["edge_spatial"] = safe_sqlite_backup(spatial_db, stage / "edge_spatial.snapshot.db")
        snapshots["edge_rag"] = safe_sqlite_backup(rag_db, stage / "edge_rag.snapshot.db")

        rag_export = export_recent_rag_outputs(
            stage / "knowledge_ledger.snapshot.db" if snapshots["knowledge_ledger"] else ledger_db,
            stage / "recent_rag_outputs.json",
            limit=max(1, args.rag_limit),
        )

        pothole_export = export_recent_pothole_coordinates(
            stage / "edge_spatial.snapshot.db" if snapshots["edge_spatial"] else spatial_db,
            stage / "recent_pothole_coordinates.json",
            limit=2000,
        )

        sla_export = export_latency_sla_metrics(
            stage / "knowledge_ledger.snapshot.db" if snapshots["knowledge_ledger"] else ledger_db,
            stage / "latency_sla_metrics.json",
            limit=3000,
        )

        if telemetry_file.exists():
            shutil.copy2(telemetry_file, stage / "telemetry_health.json")
        else:
            (stage / "telemetry_health.json").write_text(
                json.dumps({"status": "missing", "reason": "telemetry_health.json not found"}, indent=2),
                encoding="utf-8",
            )

        manifest = {
            "generated_utc": datetime.utcnow().isoformat() + "Z",
            "archive": archive_name,
            "project_root": str(project_root),
            "db_snapshots": snapshots,
            "rag_export": rag_export,
            "pothole_export": pothole_export,
            "sla_export": sla_export,
            "files": sorted([p.name for p in stage.iterdir()]),
        }
        (stage / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(stage, arcname=stage.name)

    print(json.dumps({"status": "ok", "archive": str(archive_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
