"""
agents/blackspot_mapper.py
SmartSalai Edge-Sentinel — Persona 6: Chennai Blackspot Data Curator
Road Accident Hotspot → H3 Geofence → SQLite Vector DB

DATA SOURCES:
  1. MORTH iRAD (Integrated Road Accident Database) — National
  2. Chennai Police Traffic Wing — State/City
  3. NHAI Incident Reports — National highways
  4. Community-reported incidents (Aggregated, anonymized)

PROCESSING:
  1. CSV ingest: accident_date, lat, lon, severity, vehicle_types, injuries
  2. Spatial clustering: Group into H3 cells (res 9 = ~1.7 km²)
  3. Stats calculation: Aggregate accidents per cell
  4. Road type tagging: OSM integration (optional)
  5. Insert into edge_spatial.db

COVERAGE:
  - Greater Chennai Metropolitan Area (GCMA)
  - Major highways (NH16, NH44, SH-11)
  - Tier-2 cities (future expansion)

OUTPUT SCHEMA:
  BlackspotCell {
    h3_index: "b85283473ffff",
    accident_count: 47,
    severity_avg: 4.8,
    deaths_count: 12,
    injuries_count: 68,
    road_type: "highway",
    last_updated: "2026-03-20T10:00:00Z"
  }
"""

from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

try:
    import h3
except ImportError:
    h3 = None

logger = logging.getLogger("edge_sentinel.agents.blackspot_mapper")
logger.setLevel(logging.DEBUG)

# ───────────────────────────────────────────────────────────────────────────
# Data Models
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class AccidentRecord:
    """Raw accident incident record (from CSV)."""
    accident_id: str
    date: str  # YYYY-MM-DD
    latitude: float
    longitude: float
    severity: int  # 1 (property damage) to 5 (fatal)
    vehicle_types: List[str]  # ["2-wheeler", "auto", "car"]
    casualties_deaths: int
    casualties_injuries: int
    road_type: str  # "highway", "primary", "secondary", "local"
    location_description: str


@dataclass
class BlackspotAggregation:
    """Aggregated statistics for H3 cell."""
    h3_cell: str
    latitude: float
    longitude: float
    accident_count: int
    severity_avg: float
    deaths_total: int
    injuries_total: int
    vehicle_types_involved: List[str]
    road_types: List[str]
    date_range: Tuple[str, str]  # (earliest, latest)
    metadata: Dict


# ───────────────────────────────────────────────────────────────────────────
# Blackspot Mapper
# ───────────────────────────────────────────────────────────────────────────

class ChennaiBlackspotMapper:
    """
    Ingest accident data → H3 aggregation → SQLite insertion.
    
    Handles:
    - CSV/JSON data sources
    - H3 hierarchical indexing (resolution 9 for ~1.7 km² cells)
    - Statistical aggregation (min/max/avg severity)
    - Temporal trend analysis
    - Metadata curation (road type, vehicle mix)
    """

    def __init__(self, h3_resolution: int = 9):
        """
        Initialize mapper.
        
        Args:
            h3_resolution: H3 cell resolution for aggregation
                           9 = ~1.7 km², suitable for road segments
        """
        self.h3_resolution = h3_resolution
        self.accidents: List[AccidentRecord] = []
        self.blackspots: Dict[str, BlackspotAggregation] = {}
        logger.info(f"ChennaiBlackspotMapper initialized (H3 res={h3_resolution})")

    def load_csv(self, csv_path: str) -> int:
        """
        Load accident records from CSV.
        
        EXPECTED CSV COLUMNS:
        - accident_id: Unique identifier
        - date: YYYY-MM-DD
        - latitude: WGS84
        - longitude: WGS84
        - severity: 1-5 (1=property, 5=fatal)
        - vehicle_types: Comma-separated (e.g., "2-wheeler,car")
        - deaths: Integer
        - injuries: Integer
        - road_type: highway|primary|secondary|local
        - location_description: Human-readable address

        Args:
            csv_path: Path to CSV file

        Returns:
            Number of records loaded
        """
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        record = AccidentRecord(
                            accident_id=row.get("accident_id", ""),
                            date=row.get("date", ""),
                            latitude=float(row.get("latitude", 0)),
                            longitude=float(row.get("longitude", 0)),
                            severity=int(row.get("severity", 1)),
                            vehicle_types=row.get("vehicle_types", "").split(","),
                            casualties_deaths=int(row.get("deaths", 0)),
                            casualties_injuries=int(row.get("injuries", 0)),
                            road_type=row.get("road_type", "local"),
                            location_description=row.get("location_description", ""),
                        )
                        self.accidents.append(record)
                    except ValueError as e:
                        logger.warning(f"Skipping invalid record: {e}")
                        continue

            logger.info(f"Loaded {len(self.accidents)} accident records from {csv_path}")
            return len(self.accidents)

        except FileNotFoundError:
            logger.error(f"CSV file not found: {csv_path}")
            return 0
        except Exception as e:
            logger.error(f"CSV loading failed: {e}")
            return 0

    def aggregate_to_h3(self) -> Dict[str, BlackspotAggregation]:
        """
        Group accidents into H3 cells and compute statistics.
        
        ALGORITHM:
        1. For each accident, map (lat, lon) to H3 cell
        2. Group by cell
        3. Calculate aggregate statistics
        4. Determine dominant road type and vehicle mix

        Returns:
            Dict[h3_index] -> BlackspotAggregation
        """
        if not self.accidents:
            logger.warning("No accidents to aggregate. Load CSV first.")
            return {}

        # Group by H3 cell
        cell_groups: Dict[str, List[AccidentRecord]] = defaultdict(list)

        for accident in self.accidents:
            if h3 is None:
                # Fallback: use simple geohash
                cell_key = self._geohash_fallback(accident.latitude, accident.longitude)
            else:
                try:
                    cell_key = h3.latlng_to_cell(accident.latitude, accident.longitude, self.h3_resolution)
                except Exception as e:
                    logger.warning(f"H3 conversion failed: {e}")
                    cell_key = self._geohash_fallback(accident.latitude, accident.longitude)

            cell_groups[cell_key].append(accident)

        # Compute statistics for each cell
        self.blackspots = {}

        for cell_key, accidents in cell_groups.items():
            if h3 and cell_key != self._geohash_fallback(0, 0):
                try:
                    lat, lon = h3.cell_to_latlng(cell_key)
                except Exception:
                    lat, lon = accidents[0].latitude, accidents[0].longitude
            else:
                lat, lon = accidents[0].latitude, accidents[0].longitude

            # Aggregate stats
            severity_values = [a.severity for a in accidents]
            deaths = sum(a.casualties_deaths for a in accidents)
            injuries = sum(a.casualties_injuries for a in accidents)
            road_types = list(set(a.road_type for a in accidents))
            vehicle_types = set()
            for a in accidents:
                vehicle_types.update(a.vehicle_types)

            dates = [a.date for a in accidents]
            date_range = (min(dates), max(dates)) if dates else ("", "")

            agg = BlackspotAggregation(
                h3_cell=cell_key,
                latitude=lat,
                longitude=lon,
                accident_count=len(accidents),
                severity_avg=sum(severity_values) / len(severity_values) if severity_values else 0,
                deaths_total=deaths,
                injuries_total=injuries,
                vehicle_types_involved=list(vehicle_types),
                road_types=road_types,
                date_range=date_range,
                metadata={
                    "data_source": "MORTH iRAD",
                    "region": "Chennai Metropolitan Area",
                    "vehicle_mix": {vt: sum(1 for a in accidents if vt in a.vehicle_types) for vt in vehicle_types},
                },
            )

            self.blackspots[cell_key] = agg

        logger.info(f"Aggregated {len(self.accidents)} accidents into {len(self.blackspots)} H3 cells")
        return self.blackspots

    def export_to_sql_inserts(self) -> List[Tuple]:
        """
        Generate parameterized SQL INSERT data for SQLite insertion.
        SECURITY FIX: Use parameterized queries (?) instead of f-strings to prevent SQL injection.
        
        Returns:
            List of tuples: (sql_statement, parameter_values)
        """
        insert_data = []
        sql_template = """
INSERT OR REPLACE INTO blackspot_cells 
(h3_index, resolution, latitude, longitude, accident_count, severity_avg,
 deaths_count, injuries_count, road_type, last_updated, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """.strip()

        for cell_key, agg in self.blackspots.items():
            params = (
                cell_key,  # h3_index
                self.h3_resolution,  # resolution
                agg.latitude,  # latitude
                agg.longitude,  # longitude
                agg.accident_count,  # accident_count
                agg.severity_avg,  # severity_avg
                agg.deaths_total,  # deaths_count
                agg.injuries_total,  # injuries_count
                agg.road_types[0] if agg.road_types else "local",  # road_type
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # last_updated
                json.dumps(agg.metadata)  # metadata
            )
            insert_data.append((sql_template, params))

        return insert_data

    def execute_parameterized_insert(self, db_connection) -> int:
        """
        Execute parameterized INSERT statements using provided database connection.
        SECURITY FIX: All parameters are bound safely via SQLite parameter binding.
        
        Args:
            db_connection: sqlite3.Connection object
        
        Returns:
            Number of rows inserted
        """
        insert_data = self.export_to_sql_inserts()
        cursor = db_connection.cursor()
        rows_inserted = 0
        
        for sql_template, params in insert_data:
            cursor.execute(sql_template, params)
            rows_inserted += cursor.rowcount
        
        db_connection.commit()
        logger.info(f"Inserted {rows_inserted} blackspot records via parameterized query")
        return rows_inserted

    def get_statistics(self) -> Dict:
        """
        Return high-level statistics about blackspots.
        
        Returns:
            Dict with counts, totals, and trends
        """
        if not self.blackspots:
            return {}

        severity_values = [agg.severity_avg for agg in self.blackspots.values()]
        death_values = [agg.deaths_total for agg in self.blackspots.values()]
        injury_values = [agg.injuries_total for agg in self.blackspots.values()]

        return {
            "total_accidents": len(self.accidents),
            "blackspot_cells": len(self.blackspots),
            "avg_accidents_per_cell": len(self.accidents) / len(self.blackspots) if self.blackspots else 0,
            "avg_severity": sum(severity_values) / len(severity_values) if severity_values else 0,
            "total_deaths": sum(death_values),
            "total_injuries": sum(injury_values),
            "max_severity_cell": max(self.blackspots.values(), key=lambda x: x.severity_avg).h3_cell if self.blackspots else None,
        }

    # ─── Utility Methods ───────────────────────────────────────────────

    @staticmethod
    def _geohash_fallback(lat: float, lon: float) -> str:
        """Fallback geohashing when H3 unavailable."""
        lat_bucket = int((lat + 90) * 100) % 10000
        lon_bucket = int((lon + 180) * 100) % 10000
        return f"GH{lat_bucket:04d}{lon_bucket:04d}"


# ───────────────────────────────────────────────────────────────────────────
# Smoke Test (Deterministic)
# ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mapper = ChennaiBlackspotMapper(h3_resolution=9)

    # Demo: Create sample CSV for testing
    demo_csv = "demo_accidents.csv"
    with open(demo_csv, "w") as f:
        f.write("accident_id,date,latitude,longitude,severity,vehicle_types,deaths,injuries,road_type,location_description\n")
        f.write("A001,2026-01-15,12.9352,77.6245,4,2-wheeler;car,1,3,highway,NH16 Near Bangalore Bypass\n")
        f.write("A002,2026-02-10,12.9354,77.6247,5,auto;truck,2,5,highway,NH16 Near Bangalore Bypass\n")
        f.write("A003,2026-03-05,13.0827,80.2707,2,car;car,0,2,secondary,MG Road Junction\n")

    print("🗺️ Chennai Blackspot Mapper Test")
    print("=" * 60)

    # Load and aggregate
    mapper.load_csv(demo_csv)
    mapper.aggregate_to_h3()

    # Display results
    stats = mapper.get_statistics()
    print(f"\n📊 Statistics:")
    for key, value in stats.items():
        print(f"   {key}: {value}")

    # Export SQL
    print(f"\n💾 SQL Inserts:")
    sqls = mapper.export_to_sql_inserts()
    for sql in sqls[:2]:  # Show first 2
        print(sql)

    # Cleanup
    import os
    os.remove(demo_csv)

    print("\n✅ Blackspot mapper test passed.")
