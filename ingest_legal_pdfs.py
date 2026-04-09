import os
import sys
import sqlite3
import pdfplumber
from dotenv import load_dotenv

# Initialize Env
load_dotenv()


# CONFIGURATION — override RAW_DATA_DIR via environment variable if needed
RAW_DATA_DIR = os.getenv("RAW_DATA_DIR", os.path.join(os.path.dirname(__file__), "raw_data"))
PDF_FILES = [
    "Motor Vehicle Ammendment Act 2019.pdf",
    "MOTOR VEHICLES ACTS - ADMINISTRATION 2022-2023.pdf",
    "TAMILNADU ROAD CRASH DATA.pdf"
]

def check_raw_data():
    missing = []
    for f in PDF_FILES:
        if not os.path.exists(os.path.join(RAW_DATA_DIR, f)):
            missing.append(f)
    
    if missing:
        print(f"ERR_DATA_MISSING: [Persona 6: {', '.join(missing)}]")
        sys.exit(1)

def ingest_pdfs():
    check_raw_data()
    print("PERSONA_6_REPORT: COMMENCING_LEGAL_INGESTION.")
    
    # Placeholder for SQLite-VSS initialization post-dependency verification
    # Using local vector store logic defined in edge_vector_store.py as fallback
    from edge_vector_store import EdgeVectorStore
    store = EdgeVectorStore()

    for pdf_name in PDF_FILES:
        path = os.path.join(RAW_DATA_DIR, pdf_name)
        with pdfplumber.open(path) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() + "\n"
            
            # Simple chunking for MVP
            chunks = [full_text[i:i+1000] for i in range(0, len(full_text), 800)]
            for i, chunk in enumerate(chunks):
                store.add_statute(f"{pdf_name}_chunk_{i}", chunk)
    
    print("PERSONA_6_REPORT: INGESTION_COMPLETE.")

if __name__ == "__main__":
    try:
        ingest_pdfs()
    except Exception as e:
        print(f"ERR_INTERNAL: {str(e)}")
        sys.exit(1)
