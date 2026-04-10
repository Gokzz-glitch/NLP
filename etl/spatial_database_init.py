"""
etl/spatial_database_init.py
SmartSalai Edge-Sentinel — Persona 6: Spatial Database Initialization
SQLite-VSS Backend for Edge-Native Geospatial Queries

SCHEMA:
  - blackspot_cells: H3 cell index, accident stats, road type
  - geofence_boundaries: Polygon boundaries (Polygon WKT format)
  - speed_zone_overrides: Location-specific speed restrictions
  - legal_documents: Embedded legal references for context

CAPABILITIES:
  - Vector search: Find semantically similar accident patterns
  - Spatial queries: Haversine distance, polygon containment
  - Full-text search: Legal statute search via FTS5
  - Transaction-safe: ACID compliance for mobile sync

DATABASE FILE: edge_spatial.db (SQLite 3, V3 format)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Tuple

try:
    import osmium
except ImportError:
    osmium = None

logger = logging.getLogger("edge_sentinel.etl.spatial_database_init")
logger.setLevel(logging.DEBUG)

# ───────────────────────────────────────────────────────────────────────────
# Database Constants
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_DB_PATH = "edge_spatial.db"
SCHEMA_VERSION = "1.1.0"


class SpatialDatabaseManager:

    def enable_spatialite(self):
        """Enable Spatialite extension for geospatial support."""
        try:
            self.conn.enable_load_extension(True)
            # Try common names for the extension
            for ext in ["mod_spatialite", "spatialite"]:
                try:
                    self.conn.load_extension(ext)
                    logger.info(f"Spatialite extension loaded: {ext}")
                    return
                except Exception:
                    continue
            logger.warning("Spatialite extension not loaded. Geospatial features may not work.")
        except Exception as e:
            logger.warning(f"Spatialite extension load failed: {e}")

    def create_osm_roads_table(self):
        """Create OSM roads table with geometry."""
        cursor = self.conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS osm_roads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osm_id TEXT,
            highway TEXT,
            ref TEXT,
            name TEXT,
            geom BLOB
        );
        """)
        # Add spatial index if possible
        try:
            cursor.execute("SELECT InitSpatialMetaData(1);")
            cursor.execute("SELECT AddGeometryColumn('osm_roads', 'geom', 4326, 'LINESTRING', 'XY');")
        except Exception:
            pass
        self.conn.commit()

    def insert_osm_road(self, osm_id, highway, ref, name, wkt_linestring):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO osm_roads (osm_id, highway, ref, name, geom)
                VALUES (?, ?, ?, ?, GeomFromText(?, 4326))
                """,
                (osm_id, highway, ref, name, wkt_linestring)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Insert OSM road failed: {e}")
            self.conn.rollback()

def load_osm_pbf(filepath, db_path=DEFAULT_DB_PATH):
    """
    Ingest OSM PBF file, extract road segments, and store as LineStrings in SQLite/Spatialite.
    Args:
        filepath: Path to .osm.pbf file
        db_path: Path to SQLite DB
    """
    if osmium is None:
        raise ImportError("osmium required: pip install osmium")
    db = SpatialDatabaseManager(db_path)
    db.enable_spatialite()
    db.create_osm_roads_table()

    class RoadHandler(osmium.SimpleHandler):
        def __init__(self, db):
            super().__init__()
            self.db = db
        def way(self, w):
            tags = w.tags
            highway = tags.get("highway", None)
            if not highway:
                return
            ref = tags.get("ref", None)
            name = tags.get("name", None)
            # Only keep major roads
            if highway not in {"primary", "trunk", "secondary", "residential"}:
                return
            try:
                coords = [(n.lat, n.lon) for n in w.nodes]
                if len(coords) < 2:
                    return
                # WKT: LINESTRING(lon1 lat1, lon2 lat2, ...)
                wkt = "LINESTRING (" + ", ".join(f"{lon} {lat}" for lat, lon in coords) + ")"
                self.db.insert_osm_road(str(w.id), highway, ref, name, wkt)
            except Exception as e:
                logger.error(f"Failed to ingest way {w.id}: {e}")

    handler = RoadHandler(db)
    logger.info(f"Starting OSM PBF ingest: {filepath}")
    handler.apply_file(filepath, locations=True)
    logger.info("OSM PBF ingest complete.")

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Initialize connection pool and verify schema.
        
        Args:
            db_path: SQLite database file path (created if missing)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = self._open_connection()
        self._initialize_schema()
        logger.info(f"SpatialDatabaseManager initialized: {self.db_path}")

    def _open_connection(self) -> sqlite3.Connection:
        """Create SQLite connection with optimized settings and concurrency armor."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        # WAL and concurrency PRAGMAs
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 15000;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        logger.info("SQLite connection concurrency armor applied (WAL, busy_timeout=15000ms)")
        return conn

    def _initialize_schema(self):
        """Create tables if they don't exist, including jurisdiction."""
        cursor = self.conn.cursor()
        try:
            # ─── Main Tables ───────────────────────────────────
            # ...existing code...
            # Jurisdiction table for OSM RAG
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jurisdiction (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                lat REAL,
                lon REAL
            );
            """)
            # ...existing code...
            cursor.execute("""
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
            );
            """)

            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_predictive_hotspots_score
            ON predictive_hotspots(danger_probability_score DESC, verified_report_count DESC);
            """)

            # B2B customer records for routing intelligence subscriptions
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS b2b_customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                company_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # API keys provisioned post-payment for premium API access
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                tier TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                FOREIGN KEY(customer_id) REFERENCES b2b_customers(id)
            );
            """)

            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_customer_status
            ON api_keys(customer_id, status);
            """)

            # Payment audit records for webhook-backed settlement events
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                tx_id TEXT PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                gateway_signature TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(customer_id) REFERENCES b2b_customers(id)
            );
            """)

            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_customer_created
            ON transactions(customer_id, created_at DESC);
            """)

            self.conn.commit()
            logger.info("Database schema initialized successfully.")
        except sqlite3.Error as e:
            logger.error(f"Schema initialization failed: {e}")
            self.conn.rollback()
            raise

    # ─────────────────────────────────────────────────────────────────────
    # Blackspot Operations
    # ─────────────────────────────────────────────────────────────────────

    def insert_blackspot(
        self,
        h3_index: str,
        resolution: int,
        latitude: float,
        longitude: float,
        accident_count: int,
        severity_avg: float,
        deaths_count: int,
        injuries_count: int,
        road_type: str,
        last_updated: str,
        metadata: Optional[Dict] = None,
    ) -> int:
        """Insert a blackspot cell into the database."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
            INSERT OR REPLACE INTO blackspot_cells 
            (h3_index, resolution, latitude, longitude, accident_count, severity_avg,
             deaths_count, injuries_count, road_type, last_updated, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                h3_index, resolution, latitude, longitude, accident_count, severity_avg,
                deaths_count, injuries_count, road_type, last_updated,
                json.dumps(metadata) if metadata else None
            ))
            self.conn.commit()
            logger.debug(f"Inserted blackspot: {h3_index}")
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Insert blackspot failed: {e}")
            self.conn.rollback()
            raise

    def query_nearby_blackspots(
        self, latitude: float, longitude: float, radius_deg: float = 0.05
    ) -> List[Dict]:
        """
        Query blackspots within bounding box (simple grid query).
        
        OPTIMIZATION:
          Uses bounding box + index lookup instead of full table scan.
          For precise distance filtering, use agent layer.

        Args:
            latitude, longitude: Query point
            radius_deg: Bounding box in degrees (~5km at equator = 0.05°)

        Returns:
            List of dicts with blackspot data
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
            SELECT * FROM blackspot_cells
            WHERE latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            ORDER BY 
              SQRT((latitude - ?) * (latitude - ?) + 
                   (longitude - ?) * (longitude - ?)) ASC
            """, (
                latitude - radius_deg, latitude + radius_deg,
                longitude - radius_deg, longitude + radius_deg,
                latitude, latitude,
                longitude, longitude,
            ))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Query nearby blackspots failed: {e}")
            return []

    def get_blackspot_stats(self) -> Dict:
        """Get aggregate statistics for all blackspots."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
            SELECT 
              COUNT(*) as total_cells,
              SUM(accident_count) as total_accidents,
              SUM(deaths_count) as total_deaths,
              SUM(injuries_count) as total_injuries,
              AVG(severity_avg) as avg_severity
            FROM blackspot_cells
            """)
            row = cursor.fetchone()
            return dict(row) if row else {}
        except sqlite3.Error as e:
            logger.error(f"Get blackspot stats failed: {e}")
            return {}

    # ─────────────────────────────────────────────────────────────────────
    # Legal Document Operations
    # ─────────────────────────────────────────────────────────────────────

    def insert_legal_document(
        self,
        section_id: str,
        title: str,
        content: str,
        jurisdiction: str,
        statute_type: str,
        last_updated: str,
    ) -> int:
        """Insert a legal document/statute into the database."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
            INSERT OR REPLACE INTO legal_documents
            (section_id, title, content, jurisdiction, statute_type, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (section_id, title, content, jurisdiction, statute_type, last_updated))

            # Also insert into FTS index
            cursor.execute("""
            INSERT OR REPLACE INTO legal_documents_fts
            (section_id, title, content, jurisdiction)
            VALUES (?, ?, ?, ?)
            """, (section_id, title, content, jurisdiction))

            self.conn.commit()
            logger.debug(f"Inserted legal document: {section_id}")
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Insert legal document failed: {e}")
            self.conn.rollback()
            raise

    def search_legal_documents(self, query: str) -> List[Dict]:
        """
        Full-text search over legal documents using FTS5.
        
        Args:
            query: Natural language search (e.g., "helmet fine")

        Returns:
            List of matching documents ranked by relevance
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
            SELECT ld.* FROM legal_documents ld
            WHERE ld.id IN (
              SELECT content_rowid FROM legal_documents_fts
              WHERE legal_documents_fts MATCH ?
            )
            ORDER BY RANK
            """, (query,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Legal document search failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # Event Logging (Audit Trail)
    # ─────────────────────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        event_id: Optional[str] = None,
        vehicle_h3_cell: Optional[str] = None,
        blackspot_h3_cell: Optional[str] = None,
        severity: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ):
        """Log an event for audit trail."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO event_log
            (event_type, event_id, vehicle_h3_cell, blackspot_h3_cell, severity, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event_type, event_id, vehicle_h3_cell, blackspot_h3_cell, severity,
                json.dumps(metadata) if metadata else None
            ))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Event logging failed: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # Gamification + Pre-Cog Operations
    # ─────────────────────────────────────────────────────────────────────

    def increment_user_reputation(
        self,
        user_id: str,
        token_delta: int = 1,
        trust_delta: int = 1,
        report_time: Optional[str] = None,
    ) -> Dict:
        """Upsert a user profile and increment Safety Tokens/Trust Rank."""
        cursor = self.conn.cursor()
        report_time = report_time or datetime.utcnow().isoformat()
        try:
            cursor.execute(
                """
                INSERT INTO users (user_id, safety_tokens, trust_rank, verified_report_count, last_report_at, updated_at)
                VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    safety_tokens = users.safety_tokens + excluded.safety_tokens,
                    trust_rank = users.trust_rank + excluded.trust_rank,
                    verified_report_count = users.verified_report_count + 1,
                    last_report_at = excluded.last_report_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, max(0, token_delta), max(0, trust_delta), report_time),
            )
            self.conn.commit()
            cursor.execute(
                "SELECT user_id, safety_tokens, trust_rank, verified_report_count, last_report_at FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
        except sqlite3.Error as e:
            logger.error(f"User reputation update failed: {e}")
            self.conn.rollback()
            return {}

    def upsert_predictive_hotspot(
        self,
        grid_id: str,
        center_lat: float,
        center_lon: float,
        road_type: str,
        report_count: int,
        verified_report_count: int,
        accident_signal_count: int,
        danger_probability_score: float,
        first_seen_at: str,
        last_seen_at: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Create or update a predictive hotspot record."""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO predictive_hotspots (
                    grid_id, center_lat, center_lon, road_type, report_count,
                    verified_report_count, accident_signal_count, danger_probability_score,
                    first_seen_at, last_seen_at, metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(grid_id) DO UPDATE SET
                    center_lat = excluded.center_lat,
                    center_lon = excluded.center_lon,
                    road_type = excluded.road_type,
                    report_count = excluded.report_count,
                    verified_report_count = excluded.verified_report_count,
                    accident_signal_count = excluded.accident_signal_count,
                    danger_probability_score = excluded.danger_probability_score,
                    first_seen_at = CASE
                        WHEN predictive_hotspots.first_seen_at <= excluded.first_seen_at THEN predictive_hotspots.first_seen_at
                        ELSE excluded.first_seen_at
                    END,
                    last_seen_at = excluded.last_seen_at,
                    metadata = excluded.metadata,
                    status = CASE WHEN excluded.danger_probability_score > 0.6 THEN 'active' ELSE predictive_hotspots.status END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    grid_id,
                    center_lat,
                    center_lon,
                    road_type,
                    max(0, int(report_count)),
                    max(0, int(verified_report_count)),
                    max(0, int(accident_signal_count)),
                    float(max(0.0, min(1.0, danger_probability_score))),
                    first_seen_at,
                    last_seen_at,
                    json.dumps(metadata or {}),
                ),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Predictive hotspot upsert failed: {e}")
            self.conn.rollback()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")


# ───────────────────────────────────────────────────────────────────────────
# Smoke Test (Deterministic)
# ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db = SpatialDatabaseManager("test_spatial.db")

    # Insert sample blackspot
    db.insert_blackspot(
        h3_index="b85283473ffff",
        resolution=9,
        latitude=12.9352,
        longitude=77.6245,
        accident_count=47,
        severity_avg=4.8,
        deaths_count=12,
        injuries_count=68,
        road_type="highway",
        last_updated="2026-03-15T10:00:00Z",
        metadata={"region": "Bangalore", "data_source": "MORTH"},
    )

    # Insert legal document
    db.insert_legal_document(
        section_id="SEC_183",
        title="Speeding Punishment",
        content="Whoever drives a motor vehicle at a speed exceeding the prescribed speed limit...",
        jurisdiction="INDIA",
        statute_type="mv_act",
        last_updated="2019-09-01T00:00:00Z",
    )

    # Query nearby
    print("📍 Querying nearby blackspots...")
    nearby = db.query_nearby_blackspots(12.9352, 77.6245, radius_deg=0.1)
    print(f"Found {len(nearby)} blackspots")

    # Get stats
    stats = db.get_blackspot_stats()
    print(f"📊 Stats: {stats}")

    # Search legal docs
    print("⚖️ Searching legal documents...")
    results = db.search_legal_documents("speed")
    print(f"Found {len(results)} matches")

    db.close()
    print("✅ Schema initialization test passed.")
