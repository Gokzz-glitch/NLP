import hashlib
import re
import sqlite3
import numpy as np
import json
import os

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None


class _FallbackEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def encode(self, text: str):
        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

class EdgeVectorStore:
    """
    Offline-first Vector Store replacement for SQLite-VSS.
    Uses SentenceTransformers (local) and cosine similarity in NumPy.
    """
    def __init__(self, model_name='all-MiniLM-L6-v2', db_path='legal_vector_store.db'):
        self.model_name = model_name
        self.model = self._load_model(model_name)
        self.db_path = db_path
        self._init_db()

    def _load_model(self, model_name: str):
        if SentenceTransformer is None:
            return _FallbackEmbedder()

        try:
            return SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            return _FallbackEmbedder()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.execute('PRAGMA busy_timeout=5000;')
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

    def _open_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.execute('PRAGMA busy_timeout=5000;')
        return conn

    def add_statute(self, statute_id, content):
        embedding = self.model.encode(content)
        embedding_blob = embedding.tobytes()
        
        conn = self._open_connection()
        conn.execute('INSERT INTO embeddings (statute_id, content, embedding_blob) VALUES (?, ?, ?)',
                     (statute_id, content, embedding_blob))
        conn.commit()
        conn.close()
        print(f"PERSONA_6_REPORT: EMBEDDED_STATUTE: {statute_id}")

    def query(self, query_text, top_k=3):
        query_embedding = self.model.encode(query_text)
        query_embedding = np.asarray(query_embedding, dtype=np.float32)
        
        conn = self._open_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT statute_id, content, embedding_blob FROM embeddings')
        rows = cursor.fetchall()
        
        results = []
        for statute_id, content, blob in rows:
            stored_embedding = np.frombuffer(blob, dtype=np.float32)
            if stored_embedding.shape != query_embedding.shape:
                continue
            # Manual Cosine Similarity
            denominator = np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
            if denominator == 0:
                continue
            similarity = float(np.dot(query_embedding, stored_embedding) / denominator)
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
