import sqlite3
import csv
import logging
from pathlib import Path

# [PERSONA 6: SPATIAL INGESTION]
# Ingests MoRTH accident blackspots for Chennai City.
# Data source: raw_data/chennai_accident_blackspots.csv

logger = logging.getLogger("edge_sentinel.blackspot_ingest")
logger.setLevel(logging.INFO)

# Mock Geocoding for Chennai Blackspots (as exact coords are missing in the provided CSV)
CHENNAI_GEO_MAP = {
    "C.T.H. Road Mannurpet": (13.0900, 80.1600),
    "Tambaram - Puzhal Bypass Road": (13.0300, 80.1500),
    "Nazarethpet junction": (13.0400, 80.0800),
    "Vembuli Amman koil junction": (13.0600, 80.1700)
}

def ingest_blackspots():
    db_path = "spatial_ground_truth.db"
    csv_path = "raw_data/chennai_accident_blackspots.csv"
    
    if not Path(csv_path).exists():
        logger.error(f"FILE_NOT_FOUND: {csv_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    count = 0
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader) # Skip header
        for row in reader:
            if not row: continue
            state = row[0]
            district = row[1]
            location_name = row[4]
            
            # Filter for Chennai City
            if state == "Tamilnadu" and "Chennai City" in district:
                # Find coords
                coords = (13.0827, 80.2707) # default Chennai central
                for key, val in CHENNAI_GEO_MAP.items():
                    if key in location_name:
                        coords = val
                        break
                
                cur.execute("""
                    INSERT INTO ground_truth_markers 
                    (node_id, class, lat, lon, severity, confidence, is_verified_locally, raw_metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "MORT-BLACKSPOT-2022",
                    "BLACKSPOT",
                    coords[0],
                    coords[1],
                    3, # Critical Severity
                    1.0,
                    1, # Verified by government data
                    str(row)
                ))
                count += 1
    
    conn.commit()
    conn.close()
    logger.info(f"SPATIAL_INGESTION: Loaded {count} Chennai blackspots into ground_truth_markers.")

if __name__ == "__main__":
    ingest_blackspots()
