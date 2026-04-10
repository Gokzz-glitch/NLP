import sqlite3

# Initialize osm.db with required schema and seed data for jurisdiction table
def init_osm_db(db_path="osm.db"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Create jurisdiction table
    c.execute('''
    CREATE TABLE IF NOT EXISTS jurisdiction (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        lat REAL,
        lon REAL
    );
    ''')
    # Seed with sample data if empty
    c.execute('SELECT COUNT(*) FROM jurisdiction')
    if c.fetchone()[0] == 0:
        c.executemany('''
            INSERT INTO jurisdiction (name, lat, lon) VALUES (?, ?, ?)
        ''', [
            ("Testville", 12.9716, 77.5946),
            ("Sampletown", 28.7041, 77.1025),
            ("Demo City", 19.0760, 72.8777)
        ])
        print("Seeded jurisdiction table with sample data.")
    else:
        print("Jurisdiction table already seeded.")
    conn.commit()
    conn.close()
    print(f"osm.db initialized at {db_path}")

if __name__ == "__main__":
    init_osm_db()
