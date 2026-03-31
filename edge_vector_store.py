import sqlite3
import numpy as np
import json
import os
from sentence_transformers import SentenceTransformer

class EdgeVectorStore:
    """
    Offline-first Vector Store replacement for SQLite-VSS.
    Uses SentenceTransformers (local) and cosine similarity in NumPy.
    """
    def __init__(self, model_name='all-MiniLM-L6-v2', db_path='legal_vector_store.db'):
        self.model = SentenceTransformer(model_name)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY,
                statute_id TEXT,
                content TEXT,
                embedding_blob BLOB
            )
        ''')
        conn.commit()
        conn.close()

    def add_statute(self, statute_id, content):
        embedding = self.model.encode(content)
        embedding_blob = embedding.tobytes()
        
        conn = sqlite3.connect(self.db_path)
        conn.execute('INSERT INTO embeddings (statute_id, content, embedding_blob) VALUES (?, ?, ?)',
                     (statute_id, content, embedding_blob))
        conn.commit()
        conn.close()
        print(f"PERSONA_6_REPORT: EMBEDDED_STATUTE: {statute_id}")

    def query(self, query_text, top_k=3):
        query_embedding = self.model.encode(query_text)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT statute_id, content, embedding_blob FROM embeddings')
        rows = cursor.fetchall()
        
        results = []
        for statute_id, content, blob in rows:
            stored_embedding = np.frombuffer(blob, dtype=np.float32)
            # Manual Cosine Similarity
            similarity = np.dot(query_embedding, stored_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
            )
            results.append((statute_id, content, similarity))
        
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_k]

if __name__ == "__main__":
    store = EdgeVectorStore()
    # Baseline Seeds
    store.add_statute("Sec_183", "Punishment for speeding. LMV: 1000-2000 INR. GPS telemetry is valid proof.")
    store.add_statute("Sec_194D", "Penalty for not wearing protective headgear (helmet). Fine: 1000 INR.")
    
    print("\nQUERY_TEST: 'What is the fine for speeding?'")
    print(store.query("What is the fine for speeding?"))
