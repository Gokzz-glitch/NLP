"""
etl/text_chunker.py
SmartSalai Edge-Sentinel — Persona 6: ETL Data Scavenger
Stage 2 of 4: Raw Text → Legal Chunks

FUNCTION:
  Converts raw extracted text (from pdf_extractor.py) into semantically
  coherent, retrieval-optimized chunks for vector embedding.

CHUNKING STRATEGY (Legal-Aware, Hierarchical):
  Level 0 — Document split by Section header boundaries.
             Regex: "Section X / Sec. X / SECTION X / धारा X / பிரிவு X"
  Level 1 — Sub-section split within each section block.
             Regex: "(X)" / "[X]" / "(a)/(b)/(c)" sub-clauses.
  Level 2 — Fixed-size sliding window (512 tokens / 1800 chars) with
             128-char overlap, applied if any block exceeds MAX_CHUNK_CHARS.

  Each final chunk carries structured metadata for RAG retrieval:
    - source_doc, doc_type, page_numbers, section_id,
      statutory_refs (Sec/GO/SO numbers found in chunk).

TARGET CHUNK SIZE:
  ~1800 characters (≈ 350–400 tokens for MiniLM/IndicBERT).
  This fits comfortably within sentence-transformer max_seq_length=512.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .pdf_extractor import ExtractionResult, PageText

logger = logging.getLogger("edge_sentinel.etl.text_chunker")
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CHUNK_CHARS: int = 1800   # Soft ceiling; exceeded → sliding window applied
OVERLAP_CHARS: int = 200      # Sliding window overlap for context continuity
MIN_CHUNK_CHARS: int = 80     # Chunks below this are noise — discarded

# Section boundary patterns — covers MVA text, Hindi Gazette, Tamil Gazette
_SECTION_BOUNDARY_RE = re.compile(
    r"(?:^|\n)"                                    # Start of line
    r"\s*"
    r"(?:"
    r"(?:Section|Sec\.?|SECTION)\s+\d+[A-Z]?"     # English: "Section 183A"
    r"|धारा\s+\d+[क-ह]*"                           # Hindi: "धारा 183"
    r"|பிரிவு\s+\d+"                               # Tamil: "பிரிவு 183"
    r"|CHAPTER\s+[IVXLC]+"                         # Chapter headings
    r"|(?:G\.O\.\s*\(Ms\)[\.\s]*No[\.\s]*\d+)"    # TN GO reference as section start
    r")",
    re.MULTILINE,
)

# Sub-clause patterns: "(a)", "(1)", "[iv]", "Explanation.—", "Provided that—"
_SUBCLAUSE_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    r"\([a-zA-Z0-9]{1,3}\)\s"                     # (a) / (1) / (iv)
    r"|Explanation[\.\s]*[—\-]\s*"                 # Explanation.—
    r"|Provided\s+that[\s—\-]+"                    # Provided that—
    r"|Note[\.\s]*[—\-]\s*"                        # Note.—
    r")",
    re.MULTILINE,
)

# Gazette / statutory reference pattern (for metadata tagging per chunk)
_STATUTORY_REF_RE = re.compile(
    r"(?:"
    r"Section\s+\d+[A-Z]?"                          # "Section 183A"
    r"|S\.O\.\s*\d+\s*\(E\)"                        # "S.O. 2224(E)"
    r"|G\.O\.\s*\(Ms\)[\.\s]*No[\.\s]*\d+"          # "G.O.(Ms).No.56"
    r"|MVA\s+(?:19)?(?:88|19|2019)"                 # "MVA 1988 / MVA 2019"
    r"|Art(?:icle)?\.\s*\d+"                        # "Article 21"
    r"|Rule\s+\d+"                                  # "Rule 17"
    r")",
    re.IGNORECASE,
)

# Noise patterns to strip before chunking
_NOISE_PATTERNS = [
    re.compile(r"[\f\r]"),                              # Form feeds / carriage returns
    re.compile(r"\n{3,}"),                              # Excessive blank lines → double
    re.compile(r"[ \t]{2,}"),                           # Multiple spaces → single
    re.compile(r"(?:^\s*\d+\s*$)", re.MULTILINE),      # Lone page numbers
    re.compile(
        r"(?:^|\n).*?(?:GOVERNMENT OF INDIA|सरकारी राजपत्र|அரசு இதழ்).*?(?:\n|$)",
        re.MULTILINE,
    ),   # Gazette header lines (repeated per page — structural noise)
]

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class LegalChunk:
    """
    A single text chunk ready for embedding.
    Passed downstream to embedder.py (Stage 3).
    """
    chunk_id: str                          # "{file_sha256[:8]}-p{page}-c{chunk_idx}"
    source_doc: str                        # Absolute path of source PDF
    file_sha256: str                       # Source PDF deduplication key
    doc_type: str                          # e.g. "GAZETTE_CENTRAL", "MVA_ACT"
    page_numbers: List[int]               # Pages this chunk spans
    section_id: Optional[str]             # Extracted section number, e.g. "183A"
    chunk_index: int                       # 0-based index within document
    text: str                             # Clean chunk text (ready to embed)
    char_count: int
    statutory_refs: List[str] = field(default_factory=list)  # All refs found in chunk
    gazette_ref: Optional[str] = None
    go_ref: Optional[str] = None

    @property
    def embedding_input(self) -> str:
        """
        Constructs the string fed to the embedding model.
        Prefix with doc_type + section_id for domain-aware retrieval.
        Format: "[DOC_TYPE | Sec {section_id}] {text}"
        """
        prefix_parts = [self.doc_type or "LEGAL"]
        if self.section_id:
            prefix_parts.append(f"Sec {self.section_id}")
        return f"[{' | '.join(prefix_parts)}] {self.text}"


# ---------------------------------------------------------------------------
# Text Cleaner
# ---------------------------------------------------------------------------

def _clean_text(raw: str) -> str:
    """
    Remove formatting noise from gazette-extracted text.
    Preserves legal numbering patterns and section delimiters.
    """
    text = raw
    for pattern in _NOISE_PATTERNS:
        if pattern.groups == 0:
            # Simple replacement
            try:
                if pattern.pattern in (r"[\f\r]", r"\n{3,}", r"[ \t]{2,}"):
                    text = pattern.sub(
                        "\n\n" if r"\n{3,}" in pattern.pattern
                        else " " if r"[ \t]" in pattern.pattern
                        else "",
                        text,
                    )
                else:
                    text = pattern.sub("", text)
            except re.error:
                text = pattern.sub("", text)
        else:
            text = pattern.sub("", text)
    return text.strip()


def _extract_section_id(text_block: str) -> Optional[str]:
    """
    Extract the leading section number from a text block.
    Returns e.g. "183A", "194D", None.
    """
    m = _SECTION_BOUNDARY_RE.search(text_block)
    if not m:
        return None
    # Pull the numeric part
    num_match = re.search(r"\d+[A-Z]?", m.group(0))
    return num_match.group(0) if num_match else None


def _extract_statutory_refs(text: str) -> List[str]:
    return list(dict.fromkeys(_STATUTORY_REF_RE.findall(text)))  # deduped, order-preserved


# ---------------------------------------------------------------------------
# Sliding Window Fallback
# ---------------------------------------------------------------------------

def _sliding_window_split(text: str, max_chars: int, overlap: int) -> List[str]:
    """
    Splits a text block that exceeds max_chars using a sliding window.
    Attempts to break on sentence boundaries (". " or ".\n") to prevent
    mid-sentence cuts.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Prefer to break on ". " or "\n" within last 20% of window
            search_from = start + int(max_chars * 0.80)
            best_break = -1
            for br in re.finditer(r"(?<=\.)\s+|\n", text[search_from:end]):
                best_break = search_from + br.end()
            if best_break > start:
                end = best_break
        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(chunk)
        start = end - overlap  # Slide back by overlap for context continuity
        if start < 0:
            break
    return chunks


# ---------------------------------------------------------------------------
# Main Chunker
# ---------------------------------------------------------------------------

class LegalTextChunker:
    """
    Hierarchical, section-aware chunker for Indian government legal text.

    Hierarchy:
      1. Split ExtractionResult.full_text on Section boundaries.
      2. Within each section, split on sub-clause markers.
      3. Apply sliding window if any block > MAX_CHUNK_CHARS.
      4. Discard chunks < MIN_CHUNK_CHARS (noise/headers).
      5. Annotate each LegalChunk with statutory refs + page number spans.
    """

    def __init__(
        self,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
        overlap_chars: int = OVERLAP_CHARS,
        min_chunk_chars: int = MIN_CHUNK_CHARS,
    ) -> None:
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars
        self.min_chunk_chars = min_chunk_chars

    def chunk(self, extraction: ExtractionResult) -> List[LegalChunk]:
        """
        Converts an ExtractionResult into a list of LegalChunk objects.
        """
        if not extraction.extracted_pages:
            logger.warning(f"[P6/Stage2] No pages to chunk: {extraction.source_path}")
            return []

        # Build a page→text map for page-number attribution
        page_text_map: Dict[int, str] = {
            p.page_number: _clean_text(p.raw_text)
            for p in extraction.extracted_pages
        }

        # Concatenate all pages with PAGE_BREAK markers for attribution
        # Format: "\n\n[PAGE:n]\n\n{text}"
        assembled = ""
        for page_num, text in sorted(page_text_map.items()):
            assembled += f"\n\n[PAGE:{page_num}]\n\n{text}"

        # Stage 1: Section-level split
        section_blocks = self._split_on_sections(assembled)
        logger.debug(f"[P6/Stage2] {len(section_blocks)} section blocks from {extraction.source_path}")

        all_chunks: List[LegalChunk] = []
        chunk_idx = 0

        for block_text, section_id in section_blocks:
            # Stage 2: Sub-clause split within section
            sub_blocks = self._split_on_subclauses(block_text)

            for sub_text in sub_blocks:
                # Stage 3: Sliding window if too large
                windows = _sliding_window_split(sub_text, self.max_chunk_chars, self.overlap_chars)

                for window_text in windows:
                    clean = _clean_text(window_text)

                    # Strip PAGE markers from final text but track page numbers
                    page_nums = list({
                        int(m.group(1))
                        for m in re.finditer(r"\[PAGE:(\d+)\]", clean)
                    })
                    clean = re.sub(r"\[PAGE:\d+\]", "", clean).strip()

                    if len(clean) < self.min_chunk_chars:
                        continue  # Noise — discard

                    refs = _extract_statutory_refs(clean)
                    chunk = LegalChunk(
                        chunk_id=f"{extraction.file_sha256[:8]}-c{chunk_idx:04d}",
                        source_doc=extraction.source_path,
                        file_sha256=extraction.file_sha256,
                        doc_type=extraction.doc_type or "UNKNOWN",
                        page_numbers=sorted(page_nums) or [0],
                        section_id=section_id or _extract_section_id(clean),
                        chunk_index=chunk_idx,
                        text=clean,
                        char_count=len(clean),
                        statutory_refs=refs,
                        gazette_ref=extraction.gazette_ref,
                        go_ref=extraction.go_ref,
                    )
                    all_chunks.append(chunk)
                    chunk_idx += 1

        logger.info(
            f"[P6/Stage2] Chunked {extraction.source_path} → "
            f"{len(all_chunks)} chunks (avg {int(sum(c.char_count for c in all_chunks)/(len(all_chunks) or 1))} chars)"
        )
        return all_chunks

    # ------------------------------------------------------------------
    # Split helpers
    # ------------------------------------------------------------------

    def _split_on_sections(self, text: str) -> List[Tuple[str, Optional[str]]]:
        """
        Splits text on Section boundaries.
        Returns list of (block_text, section_id).
        """
        splits = list(_SECTION_BOUNDARY_RE.finditer(text))
        if not splits:
            # No section headers found — treat entire text as one block
            return [(text, None)]

        blocks: List[Tuple[str, Optional[str]]] = []

        # Pre-section preamble (before first header)
        if splits[0].start() > 0:
            preamble = text[:splits[0].start()].strip()
            if preamble:
                blocks.append((preamble, None))

        for i, match in enumerate(splits):
            start = match.start()
            end   = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            block = text[start:end]
            sec_id = _extract_section_id(match.group(0))
            blocks.append((block, sec_id))

        return blocks

    def _split_on_subclauses(self, text: str) -> List[str]:
        """
        Splits a section block on sub-clause markers.
        Returns list of sub-block strings.
        """
        splits = list(_SUBCLAUSE_RE.finditer(text))
        if not splits:
            return [text]

        blocks: List[str] = []
        if splits[0].start() > 0:
            preamble = text[:splits[0].start()].strip()
            if preamble:
                blocks.append(preamble)

        for i, match in enumerate(splits):
            start = match.start()
            end   = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            blocks.append(text[start:end])

        return blocks


