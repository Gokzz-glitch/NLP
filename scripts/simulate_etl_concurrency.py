#!/usr/bin/env python3
"""Concurrent ETL simulation with lightweight stubs.

Runs N workers calling ETLPipeline.run_once simultaneously and reports
claim/processed/failed/conflict metrics.
"""
from __future__ import annotations

import argparse
import os
import json
import tempfile
import threading
import time
import types
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---- Lightweight dependency stubs for constrained environments ----
if "numpy" not in sys.modules:
    fake_np = types.SimpleNamespace(
        float32=float,
        ndarray=object,
        array=lambda x, dtype=None: x,
    )
    sys.modules["numpy"] = fake_np

if "pdfplumber" not in sys.modules:
    class _FakeOpen:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        is_encrypted = False
        pages = []
    fake_pdfminer = types.SimpleNamespace(pdfparser=types.SimpleNamespace(PDFSyntaxError=Exception))
    sys.modules["pdfplumber"] = types.SimpleNamespace(open=lambda *_a, **_k: _FakeOpen(), pdfminer=fake_pdfminer)

from etl.pipeline import ETLPipeline
from etl.pdf_extractor import ExtractionResult, ExtractionStatus, PageText, ExtractionMethod
from etl.text_chunker import LegalChunk
from etl.embedder import EmbeddingResult


class Vec:
    def __init__(self, n=384):
        self.n = n
    def tolist(self):
        return [1.0] * self.n
    def __len__(self):
        return self.n


def run_sim(workers: int, files: int):
    base = Path(tempfile.mkdtemp(prefix="etl_sim_"))
    raw = base / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (raw / f"doc_{i}.pdf").write_bytes(b"%PDF-sim")

    db = str(base / "edge_rag.db")
    pipelines = []
    for i in range(workers):
        p = ETLPipeline(db_path=db)
        def make_extract(uid):
            def _extract(path):
                txt = f"Section 183 uid={uid} " + ("x" * 200)
                page = PageText(page_number=1, raw_text=txt, method=ExtractionMethod.DIGITAL_PDFPLUMBER, char_count=len(txt))
                return ExtractionResult(source_path=str(path), file_sha256=f"sha-{Path(path).stem}", total_pages=1, extracted_pages=[page], status=ExtractionStatus.SUCCESS, doc_type="MVA_ACT")
            return _extract
        p.extractor.extract = make_extract(i)
        p.chunker.chunk = lambda result: [LegalChunk(chunk_id=f"{result.file_sha256}-c0", source_doc=result.source_path, file_sha256=result.file_sha256, doc_type="MVA_ACT", page_numbers=[1], section_id="183", chunk_index=0, text="legal " * 120, char_count=720)]
        p.embedder.load = lambda: None
        p.embedder.embed_chunks = lambda chunks: [EmbeddingResult(chunk_id=chunks[0].chunk_id, vector=Vec(), embedding_dim=384, model_id="SIM", inference_time_ms=0.1, chunk_ref=chunks[0])]
        pipelines.append(p)

    results = []
    lock = threading.Lock()

    def worker(idx):
        m = pipelines[idx].run_once(str(raw))
        with lock:
            results.append(m)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    elapsed = time.time() - t0

    aggregate = {"claimed": 0, "reclaimed_stale": 0, "processed": 0, "failed": 0, "claim_conflicts": 0}
    for r in results:
        for k in aggregate:
            aggregate[k] += int(r.get(k, 0))

    out = {
        "workers": workers,
        "input_files": files,
        "elapsed_sec": round(elapsed, 3),
        "aggregate": aggregate,
        "worker_results": results,
        "tmp_dir": str(base),
    }
    print(json.dumps(out, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--files", type=int, default=5)
    args = ap.parse_args()
    run_sim(args.workers, args.files)


if __name__ == "__main__":
    main()
