from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger("edge_sentinel.precog_engine")


class PreCogEngine:
    """Periodic hotspot predictor that writes scored spatial grids to SQLite."""

    def __init__(self, db_path: str = "edge_spatial.db", interval_sec: int = 300, grid_size_deg: float = 0.01):
        self.db_path = Path(db_path)
        self.interval_sec = max(30, int(interval_sec))
        self.grid_size_deg = max(0.001, float(grid_size_deg))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS predictive_hotspots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grid_id TEXT UNIQUE NOT NULL,
                center_lat REAL NOT NULL,
                center_lon REAL NOT NULL,
                road_type TEXT,
                report_count INTEGER NOT NULL DEFAULT 0,
                verified_report_count INTEGER NOT NULL DEFAULT 0,
                accident_signal_count INTEGER NOT NULL DEFAULT 0,
                danger_probability_score REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'active',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                metadata JSON,
                rti_status TEXT NOT NULL DEFAULT 'pending',
                rti_generated_at TEXT,
                rti_document_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

    def _grid_for(self, lat: float, lon: float) -> Tuple[str, float, float]:
        lat_bin = round(lat / self.grid_size_deg) * self.grid_size_deg
        lon_bin = round(lon / self.grid_size_deg) * self.grid_size_deg
        grid_id = f"{lat_bin:.4f}:{lon_bin:.4f}"
        return grid_id, lat_bin, lon_bin

    def _fetch_accident_signals(self, conn: sqlite3.Connection) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT latitude AS lat, longitude AS lon, road_type, accident_count,
                   severity_avg, COALESCE(last_updated, created_at) AS event_ts
            FROM blackspot_cells
            """
        )
        return cursor.fetchall()

    def _fetch_swarm_signals(self, conn: sqlite3.Connection) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                json_extract(metadata, '$.lat') AS lat,
                json_extract(metadata, '$.lon') AS lon,
                json_extract(metadata, '$.road_type') AS road_type,
                COALESCE(severity, 0.5) AS severity,
                timestamp AS event_ts
            FROM event_log
            WHERE event_type IN ('verified_swarm_report', 'SENTINEL_FUSION_ALERT', 'hazard_report')
            """
        )
        return [row for row in cursor.fetchall() if row["lat"] is not None and row["lon"] is not None]

    def _upsert_hotspots(self, conn: sqlite3.Connection, records: Dict[str, Dict]) -> int:
        cursor = conn.cursor()
        updated = 0
        for grid_id, rec in records.items():
            score = max(0.0, min(1.0, float(rec["danger_probability_score"])))
            cursor.execute(
                """
                INSERT INTO predictive_hotspots (
                    grid_id, center_lat, center_lon, road_type, report_count, verified_report_count,
                    accident_signal_count, danger_probability_score, status, first_seen_at, last_seen_at,
                    metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(grid_id) DO UPDATE SET
                    center_lat = excluded.center_lat,
                    center_lon = excluded.center_lon,
                    road_type = excluded.road_type,
                    report_count = excluded.report_count,
                    verified_report_count = excluded.verified_report_count,
                    accident_signal_count = excluded.accident_signal_count,
                    danger_probability_score = excluded.danger_probability_score,
                    status = excluded.status,
                    first_seen_at = CASE
                        WHEN predictive_hotspots.first_seen_at <= excluded.first_seen_at THEN predictive_hotspots.first_seen_at
                        ELSE excluded.first_seen_at
                    END,
                    last_seen_at = excluded.last_seen_at,
                    metadata = excluded.metadata,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    grid_id,
                    rec["center_lat"],
                    rec["center_lon"],
                    rec["road_type"],
                    rec["report_count"],
                    rec["verified_report_count"],
                    rec["accident_signal_count"],
                    score,
                    "critical" if score >= 0.75 else ("elevated" if score >= 0.45 else "watch"),
                    rec["first_seen_at"],
                    rec["last_seen_at"],
                    json.dumps(rec["metadata"]),
                ),
            )
            updated += 1
        conn.commit()
        return updated

    def run_cycle(self) -> int:
        conn = self._connect()
        try:
            self._ensure_tables(conn)
            grouped: Dict[str, Dict] = defaultdict(
                lambda: {
                    "center_lat": 0.0,
                    "center_lon": 0.0,
                    "road_type": "unknown",
                    "report_count": 0,
                    "verified_report_count": 0,
                    "accident_signal_count": 0,
                    "severity_sum": 0.0,
                    "first_seen_at": datetime.utcnow().isoformat(),
                    "last_seen_at": datetime.utcnow().isoformat(),
                    "metadata": {"sources": []},
                }
            )

            for row in self._fetch_accident_signals(conn):
                grid_id, lat_c, lon_c = self._grid_for(float(row["lat"]), float(row["lon"]))
                rec = grouped[grid_id]
                rec["center_lat"] = lat_c
                rec["center_lon"] = lon_c
                rec["road_type"] = row["road_type"] or rec["road_type"]
                rec["accident_signal_count"] += int(row["accident_count"] or 0)
                rec["severity_sum"] += float(row["severity_avg"] or 0.0)
                rec["metadata"]["sources"].append("blackspot_cells")
                ts = row["event_ts"] or datetime.utcnow().isoformat()
                rec["first_seen_at"] = min(rec["first_seen_at"], ts)
                rec["last_seen_at"] = max(rec["last_seen_at"], ts)

            for row in self._fetch_swarm_signals(conn):
                grid_id, lat_c, lon_c = self._grid_for(float(row["lat"]), float(row["lon"]))
                rec = grouped[grid_id]
                rec["center_lat"] = lat_c
                rec["center_lon"] = lon_c
                if row["road_type"]:
                    rec["road_type"] = str(row["road_type"])
                rec["report_count"] += 1
                rec["verified_report_count"] += 1
                rec["severity_sum"] += float(row["severity"] or 0.0)
                rec["metadata"]["sources"].append("event_log")
                ts = row["event_ts"] or datetime.utcnow().isoformat()
                rec["first_seen_at"] = min(rec["first_seen_at"], ts)
                rec["last_seen_at"] = max(rec["last_seen_at"], ts)

            for rec in grouped.values():
                signal_volume = rec["report_count"] + rec["accident_signal_count"]
                mean_severity = rec["severity_sum"] / max(1, signal_volume)
                volume_score = min(1.0, signal_volume / 20.0)
                severity_score = min(1.0, mean_severity / 5.0)
                verification_score = min(1.0, rec["verified_report_count"] / 10.0)
                rec["danger_probability_score"] = round((0.5 * volume_score) + (0.25 * severity_score) + (0.25 * verification_score), 4)

            return self._upsert_hotspots(conn, grouped)
        finally:
            conn.close()

    def run_forever(self) -> None:
        logger.info("PRECOG_ENGINE_ONLINE | db=%s | interval_sec=%s", self.db_path, self.interval_sec)
        while not self._stop.is_set():
            try:
                updated = self.run_cycle()
                logger.info("PRECOG_ENGINE_CYCLE_OK | hotspots_upserted=%s", updated)
            except Exception as exc:
                logger.error("PRECOG_ENGINE_CYCLE_FAIL: %s", exc)
            self._stop.wait(self.interval_sec)

    def start_background(self) -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(target=self.run_forever, daemon=True, name="PreCogEngine")
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the predictive hotspot (Pre-Cog) engine")
    parser.add_argument("--db-path", default="edge_spatial.db")
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--grid-size-deg", type=float, default=0.01)
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    engine = PreCogEngine(db_path=args.db_path, interval_sec=args.interval_sec, grid_size_deg=args.grid_size_deg)
    if args.once:
        updated = engine.run_cycle()
        logger.info("PRECOG_ENGINE_SINGLE_RUN_DONE | hotspots_upserted=%s", updated)
        return

    engine.run_forever()


if __name__ == "__main__":
    main()
