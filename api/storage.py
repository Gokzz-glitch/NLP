"""SQLite persistence for the production API server."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_VERSION = "1"

_DDL = """
CREATE TABLE IF NOT EXISTS api_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at_epoch_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    hazard_class TEXT,
    confidence REAL,
    gps_lat REAL,
    gps_lon REAL,
    event_timestamp REAL,
    received_at_epoch_ms INTEGER NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telem_received ON telemetry_events(received_at_epoch_ms DESC);
CREATE INDEX IF NOT EXISTS idx_telem_hazard ON telemetry_events(hazard_class, received_at_epoch_ms DESC);
"""


class APIDatabase:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=10000;")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def migrate(self) -> None:
        conn = self.connect()
        with self._lock:
            conn.executescript(_DDL)
            conn.execute(
                """
                INSERT INTO api_schema_meta(key, value, updated_at_epoch_ms)
                VALUES('schema_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value=excluded.value,
                  updated_at_epoch_ms=excluded.updated_at_epoch_ms
                """,
                (SCHEMA_VERSION, int(time.time() * 1000)),
            )
            conn.commit()

    def insert_telemetry(self, payload: Dict[str, Any]) -> None:
        conn = self.connect()
        event_timestamp = payload.get("timestamp")
        if event_timestamp is None:
            event_timestamp = time.time()
        now_ms = int(time.time() * 1000)
        with self._lock:
            conn.execute(
                """
                INSERT INTO telemetry_events(
                    node_id,event_type,hazard_class,confidence,gps_lat,gps_lon,
                    event_timestamp,received_at_epoch_ms,raw_json
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(payload.get("node_id", "")),
                    str(payload.get("event_type", "")),
                    payload.get("hazard_class"),
                    payload.get("confidence"),
                    payload.get("gps_lat"),
                    payload.get("gps_lon"),
                    float(event_timestamp),
                    now_ms,
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
            conn.commit()

    def query_recent_hazards(self, window_seconds: int, limit: int) -> List[Dict[str, Any]]:
        conn = self.connect()
        cutoff = time.time() - max(0, int(window_seconds))
        with self._lock:
            rows = conn.execute(
                """
                SELECT id,node_id,event_type,hazard_class,confidence,gps_lat,gps_lon,
                       event_timestamp,received_at_epoch_ms
                FROM telemetry_events
                WHERE event_timestamp >= ?
                  AND (
                    hazard_class IS NOT NULL
                    OR lower(event_type) LIKE '%hazard%'
                    OR lower(event_type) LIKE '%pothole%'
                    OR lower(event_type) LIKE '%near_miss%'
                  )
                ORDER BY event_timestamp DESC
                LIMIT ?
                """,
                (float(cutoff), int(limit)),
            ).fetchall()

        hazards: List[Dict[str, Any]] = []
        for row in rows:
            hazards.append(
                {
                    "id": row["id"],
                    "node_id": row["node_id"],
                    "event_type": row["event_type"],
                    "hazard_class": row["hazard_class"],
                    "confidence": row["confidence"],
                    "gps_lat": row["gps_lat"],
                    "gps_lon": row["gps_lon"],
                    "event_timestamp": row["event_timestamp"],
                    "received_at_epoch_ms": row["received_at_epoch_ms"],
                }
            )
        return hazards

    def metrics_summary(self) -> Dict[str, Any]:
        conn = self.connect()
        with self._lock:
            total_events = conn.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]
            last_hour = conn.execute(
                "SELECT COUNT(*) FROM telemetry_events WHERE event_timestamp >= ?",
                (time.time() - 3600,),
            ).fetchone()[0]
            schema_version = conn.execute(
                "SELECT value FROM api_schema_meta WHERE key='schema_version'"
            ).fetchone()

        return {
            "db_path": self.db_path,
            "schema_version": schema_version[0] if schema_version else "unknown",
            "total_events": int(total_events),
            "events_last_hour": int(last_hour),
        }

    def backup_to(self, destination_path: str) -> str:
        source = self.connect()
        destination = sqlite3.connect(destination_path)
        with self._lock:
            source.backup(destination)
            destination.commit()
            destination.close()
        return os.path.abspath(destination_path)
