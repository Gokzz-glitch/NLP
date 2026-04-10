from __future__ import annotations

import json
import logging
import os
import sqlite3
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import urllib.request

logger = logging.getLogger("edge_sentinel.rti_drafter")


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_simple_pdf(lines: List[str], output_path: Path) -> None:
    """Write a minimal one-page PDF without external dependencies."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    y = 780
    content_lines = ["BT", "/F1 10 Tf"]
    for line in lines:
        wrapped = textwrap.wrap(line, width=95) or [""]
        for part in wrapped:
            content_lines.append(f"1 0 0 1 50 {y} Tm ({_escape_pdf_text(part)}) Tj")
            y -= 14
            if y < 50:
                break
        if y < 50:
            break
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("utf-8")

    objects = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n")
    objects.append(b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n")
    objects.append(f"4 0 obj<< /Length {len(content)} >>stream\n".encode("utf-8") + content + b"\nendstream endobj\n")
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    buffer = bytearray(b"%PDF-1.4\n")
    xref_positions = [0]
    for obj in objects:
        xref_positions.append(len(buffer))
        buffer.extend(obj)

    xref_start = len(buffer)
    buffer.extend(f"xref\n0 {len(xref_positions)}\n".encode("utf-8"))
    buffer.extend(b"0000000000 65535 f \n")
    for pos in xref_positions[1:]:
        buffer.extend(f"{pos:010d} 00000 n \n".encode("utf-8"))

    buffer.extend(
        (
            "trailer\n"
            f"<< /Size {len(xref_positions)} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n"
            "%%EOF"
        ).encode("utf-8")
    )

    output_path.write_bytes(bytes(buffer))


class RTIDrafter:
    """Autonomously drafts RTI letters for persistent high-risk predictive hotspots."""

    def __init__(self, db_path: str = "edge_spatial.db", scan_interval_sec: int = 3600):
        self.db_path = Path(db_path)
        self.scan_interval_sec = max(300, int(scan_interval_sec))
        self.output_dir = Path("reports") / "rti"
        self.llm_endpoint = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/api/generate")
        self.llm_models = [m.strip() for m in os.getenv("LOCAL_LLM_MODELS", "phi3:mini,gemma:2b").split(",") if m.strip()]
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _eligible_hotspots(self, conn: sqlite3.Connection) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM predictive_hotspots
            WHERE verified_report_count > 5
              AND (julianday('now') - julianday(first_seen_at)) > 7
              AND COALESCE(rti_status, 'pending') != 'generated'
            ORDER BY danger_probability_score DESC, verified_report_count DESC
            """
        )
        return cursor.fetchall()

    def _resolve_road_type(self, conn: sqlite3.Connection, hotspot: sqlite3.Row) -> str:
        if hotspot["road_type"]:
            return str(hotspot["road_type"])

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT road_type
            FROM blackspot_cells
            ORDER BY ((latitude - ?) * (latitude - ?) + (longitude - ?) * (longitude - ?)) ASC
            LIMIT 1
            """,
            (hotspot["center_lat"], hotspot["center_lat"], hotspot["center_lon"], hotspot["center_lon"]),
        )
        row = cursor.fetchone()
        if row and row["road_type"]:
            return str(row["road_type"])
        return "unknown"

    def _llm_draft(self, prompt: str) -> str:
        payload = {"prompt": prompt, "stream": False}
        for model in self.llm_models:
            try:
                body = json.dumps({**payload, "model": model}).encode("utf-8")
                req = urllib.request.Request(
                    self.llm_endpoint,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read().decode("utf-8")
                    parsed = json.loads(raw)
                    text = parsed.get("response") or parsed.get("text")
                    if text:
                        return str(text).strip()
            except Exception:
                continue
        return ""

    def _compose_rti_text(self, hotspot: sqlite3.Row, road_type: str) -> str:
        prompt = (
            "Draft a formal Indian Right to Information request letter addressed to the local Executive Engineer. "
            "The letter must request repair budget sanction details, contractor details, and work order timeline for a road hazard hotspot. "
            "Use respectful legal tone and include explicit numbered information requests.\n"
            f"Coordinates: {hotspot['center_lat']}, {hotspot['center_lon']}\n"
            f"Road type: {road_type}\n"
            f"Danger score: {hotspot['danger_probability_score']}\n"
            f"Verified reports: {hotspot['verified_report_count']}\n"
            f"First seen: {hotspot['first_seen_at']}"
        )
        llm_text = self._llm_draft(prompt)
        if llm_text:
            return llm_text

        return textwrap.dedent(
            f"""
            To,
            The Executive Engineer,
            Highways / Local Road Division

            Subject: Right to Information Application regarding unresolved hazardous road segment

            Sir/Madam,

            Under the Right to Information Act, 2005, I seek certified information regarding an unresolved public-safety hotspot.

            Hotspot Coordinates: {hotspot['center_lat']}, {hotspot['center_lon']}
            Road Type: {road_type}
            Danger Probability Score: {hotspot['danger_probability_score']}
            Verified Swarm Reports: {hotspot['verified_report_count']}
            First Recorded Date: {hotspot['first_seen_at']}

            Information Requested:
            1. Certified copy of sanctioned budget for repairs at the above location.
            2. Name and contract details of the contractor assigned to execute the repairs.
            3. Copy of work order, issue date, and expected completion date.
            4. Reasons for delay, if repair has not yet been executed.
            5. Name and designation of the officer responsible for project monitoring.

            Kindly provide the above information within the statutory timeline under the RTI Act, 2005.

            Sincerely,
            Citizen Safety Monitoring Cell
            """
        ).strip()

    def _mark_generated(self, conn: sqlite3.Connection, hotspot_id: int, pdf_path: Path) -> None:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE predictive_hotspots
            SET rti_status = 'generated',
                rti_generated_at = CURRENT_TIMESTAMP,
                rti_document_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(pdf_path), hotspot_id),
        )
        conn.commit()

    def run_cycle(self) -> int:
        conn = self._connect()
        generated = 0
        try:
            for hotspot in self._eligible_hotspots(conn):
                road_type = self._resolve_road_type(conn, hotspot)
                rti_text = self._compose_rti_text(hotspot, road_type)

                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                out_name = f"rti_hotspot_{hotspot['id']}_{ts}.pdf"
                out_path = self.output_dir / out_name
                lines = [line.strip() for line in rti_text.splitlines()]
                _write_simple_pdf(lines, out_path)

                self._mark_generated(conn, int(hotspot["id"]), out_path)
                generated += 1
                logger.info("RTI_DRAFTER_GENERATED | hotspot_id=%s | file=%s", hotspot["id"], out_path)
        finally:
            conn.close()

        return generated

    def run_forever(self) -> None:
        logger.info("RTI_DRAFTER_ONLINE | db=%s | interval_sec=%s", self.db_path, self.scan_interval_sec)
        while not self._stop.is_set():
            try:
                generated = self.run_cycle()
                logger.info("RTI_DRAFTER_CYCLE_OK | generated=%s", generated)
            except Exception as exc:
                logger.error("RTI_DRAFTER_CYCLE_FAIL: %s", exc)
            self._stop.wait(self.scan_interval_sec)

    def start_background(self) -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(target=self.run_forever, daemon=True, name="RTIDrafter")
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()
