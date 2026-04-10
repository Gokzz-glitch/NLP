import sqlite3
import datetime

def seed_pothole_law():
    conn = sqlite3.connect('legal_vector_store.db')
    cursor = conn.cursor()
    
    # Check if table exists, create if not
    cursor.execute('DROP TABLE IF EXISTS legal_statutes')
    cursor.execute('''
        CREATE TABLE legal_statutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            section TEXT,
            description TEXT,
            penalty TEXT,
            year INTEGER
        )
    ''')
    
    # Insert Section 198A regarding road contractor negligence
    cursor.execute('''
        INSERT INTO legal_statutes (source, section, description, penalty, year)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        "MVA_2019",
        "Section 198A",
        "Failure to comply with standards for road design, construction and maintenance. Any contractor, consultant, or concessionaire designated by the authority responsible for road design or construction who fails to follow prescribed standards resulting in death or disability.",
        "Fine up to ₹1,00,000. Driver Guideline: Immediately preserve dashcam footage, IMU impact data, and exact GPS coordinates to file an FIR and municipality lawsuit under this section.",
        2019
    ))
    
    conn.commit()
    conn.close()
    print("Pothole Legal RAG Database updated successfully with MVA Sec 198A (Road Contractor Negligence).")

if __name__ == '__main__':
    seed_pothole_law()
