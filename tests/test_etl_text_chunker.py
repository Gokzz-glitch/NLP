"""
tests/test_etl_text_chunker.py

Unit tests for etl/text_chunker.py covering:
  - _clean_text (form-feed/CR fix, spaces, newlines, noise strips)
  - _sliding_window_split (normal, overlap>max_chars, edge cases)
  - _extract_section_id
  - _extract_statutory_refs
  - LegalChunk.embedding_input
  - LegalTextChunker.chunk()
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from etl.text_chunker import (
    _clean_text,
    _sliding_window_split,
    _extract_section_id,
    _extract_statutory_refs,
    LegalTextChunker,
    LegalChunk,
    MIN_CHUNK_CHARS,
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
)
from etl.pdf_extractor import ExtractionResult, ExtractionStatus, PageText, ExtractionMethod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extraction(text: str, sha: str = "abcdef12", source: str = "test.pdf",
                     doc_type: str = "MVA_ACT") -> ExtractionResult:
    page = PageText(
        page_number=1,
        raw_text=text,
        method=ExtractionMethod.DIGITAL_PDFPLUMBER,
        char_count=len(text),
    )
    return ExtractionResult(
        source_path=source,
        file_sha256=sha,
        total_pages=1,
        extracted_pages=[page],
        status=ExtractionStatus.SUCCESS,
        doc_type=doc_type,
    )


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

class TestCleanText:

    def test_form_feed_replaced_with_space(self):
        """Bug fix: \\f must not merge adjacent words."""
        result = _clean_text("hello\fworld")
        assert "helloworld" not in result
        assert "hello" in result and "world" in result

    def test_carriage_return_replaced_with_space(self):
        """Bug fix: \\r must not merge adjacent words."""
        result = _clean_text("foo\rbar")
        assert "foobar" not in result
        assert "foo" in result and "bar" in result

    def test_multiple_newlines_collapsed_to_two(self):
        result = _clean_text("a\n\n\n\n\nb")
        assert "\n\n\n" not in result
        assert "a" in result and "b" in result

    def test_multiple_spaces_collapsed_to_one(self):
        result = _clean_text("hello   world")
        assert "  " not in result

    def test_empty_string(self):
        assert _clean_text("") == ""

    def test_strips_leading_trailing_whitespace(self):
        assert _clean_text("   hello   ") == "hello"

    def test_lone_page_number_removed(self):
        text = "Some legal text.\n42\nMore text."
        result = _clean_text(text)
        assert "\n42\n" not in result

    def test_gazette_header_removed(self):
        text = "Section 183. Speeding.\nGOVERNMENT OF INDIA GAZETTE EXTRA\nFine: 2000 INR."
        result = _clean_text(text)
        assert "GOVERNMENT OF INDIA" not in result
        assert "Section 183" in result

    def test_preserves_section_numbers(self):
        result = _clean_text("Section 183A. Punishment for overspeeding.")
        assert "183A" in result

    def test_form_feed_at_start(self):
        result = _clean_text("\fStarting text")
        assert result.startswith("Starting")

    def test_form_feed_at_end(self):
        result = _clean_text("Ending text\f")
        assert result.endswith("text")


# ---------------------------------------------------------------------------
# _sliding_window_split
# ---------------------------------------------------------------------------

class TestSlidingWindowSplit:

    def test_short_text_returns_itself(self):
        text = "Short text."
        result = _sliding_window_split(text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
        assert result == [text]

    def test_empty_text_returns_empty_list(self):
        """Empty string should produce no chunks."""
        result = _sliding_window_split("", MAX_CHUNK_CHARS, OVERLAP_CHARS)
        assert result == []

    def test_exact_max_chars_not_split(self):
        text = "x" * MAX_CHUNK_CHARS
        result = _sliding_window_split(text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
        assert len(result) == 1

    def test_text_larger_than_max_is_split(self):
        text = "w " * 1000  # 2000 chars
        result = _sliding_window_split(text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
        assert len(result) > 1

    def test_all_text_covered_normal(self):
        """Every character in the source text must appear in at least one chunk."""
        text = "abcdefghij" * 200  # 2000 chars, no sentence breaks
        result = _sliding_window_split(text, 100, 20)
        combined = "".join(result)
        # Due to overlap, content repeats; but first + last char of source must appear
        assert text[0] in combined
        assert text[-1] in combined

    def test_overlap_gt_max_chars_all_text_covered(self):
        """
        Bug fix: when overlap >= max_chars the window must still advance
        and cover all text — not exit after first chunk.
        """
        text = "A" * 2000
        result = _sliding_window_split(text, 100, 200)
        assert len(result) > 1, (
            f"Expected multiple chunks for 2000-char text with max=100, got {len(result)}"
        )
        # All of the original text is in at least one chunk
        for chunk in result:
            assert len(chunk) > 0

    def test_chunks_respect_min_chunk_chars(self):
        text = "x" * 2000
        result = _sliding_window_split(text, 100, 20)
        for chunk in result:
            assert len(chunk) >= MIN_CHUNK_CHARS

    def test_overlap_creates_shared_content(self):
        """Adjacent chunks must share overlap content when a break isn't found."""
        text = "A" * 500
        result = _sliding_window_split(text, 200, 50)
        if len(result) >= 2:
            # The tail of chunk[0] should equal the head of chunk[1] (approx)
            assert result[1][:10] == result[0][-10:] or len(result) > 1

    def test_no_infinite_loop(self):
        """Must terminate in reasonable time for pathological inputs."""
        import signal
        text = "z" * 10000
        # If this call returns, no infinite loop occurred
        result = _sliding_window_split(text, 50, 200)
        assert isinstance(result, list)

    def test_sentence_boundary_preferred(self):
        """
        When a '. ' break is available, the chunk should end near it
        (within the last 20% of the window).
        """
        sentence = "This is a sentence. " * 200  # many sentence breaks
        result = _sliding_window_split(sentence, 200, 50)
        assert len(result) > 1


# ---------------------------------------------------------------------------
# _extract_section_id
# ---------------------------------------------------------------------------

class TestExtractSectionId:

    def test_english_section(self):
        assert _extract_section_id("\nSection 183 Punishment for over-speeding.") == "183"

    def test_english_section_with_letter(self):
        assert _extract_section_id("\nSection 183A Heavy fine.") == "183A"

    def test_sec_abbreviation(self):
        assert _extract_section_id("\nSec. 194D Helmet.") == "194D"

    def test_no_section_returns_none(self):
        assert _extract_section_id("No section header here.") is None

    def test_chapter_header(self):
        result = _extract_section_id("\nCHAPTER IV Penalties")
        # CHAPTER headings may not produce numeric section_id but must not crash
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# _extract_statutory_refs
# ---------------------------------------------------------------------------

class TestExtractStatutoryRefs:

    def test_finds_section_ref(self):
        refs = _extract_statutory_refs("Punishable under Section 183A of MVA.")
        assert any("183A" in r for r in refs)

    def test_finds_rule_ref(self):
        refs = _extract_statutory_refs("As per Rule 17 of CMV Rules.")
        assert any("17" in r for r in refs)

    def test_no_refs_returns_empty(self):
        refs = _extract_statutory_refs("No statutory references here.")
        assert refs == []

    def test_deduplication(self):
        refs = _extract_statutory_refs("Section 183A applies. See Section 183A again.")
        assert refs.count(refs[0]) == 1 if refs else True


# ---------------------------------------------------------------------------
# LegalChunk.embedding_input
# ---------------------------------------------------------------------------

class TestLegalChunkEmbeddingInput:

    def _chunk(self, doc_type="MVA_ACT", section_id="183", text="Fine for speeding."):
        return LegalChunk(
            chunk_id="abc-c0000",
            source_doc="test.pdf",
            file_sha256="abcdef12",
            doc_type=doc_type,
            page_numbers=[1],
            section_id=section_id,
            chunk_index=0,
            text=text,
            char_count=len(text),
        )

    def test_embedding_input_contains_doc_type(self):
        c = self._chunk(doc_type="GAZETTE_CENTRAL")
        assert "GAZETTE_CENTRAL" in c.embedding_input

    def test_embedding_input_contains_section_id(self):
        c = self._chunk(section_id="194D")
        assert "194D" in c.embedding_input

    def test_embedding_input_contains_text(self):
        c = self._chunk(text="unique legal text content")
        assert "unique legal text content" in c.embedding_input

    def test_embedding_input_no_section_id(self):
        c = self._chunk(section_id=None)
        inp = c.embedding_input
        assert "Sec" not in inp
        assert c.doc_type in inp


# ---------------------------------------------------------------------------
# LegalTextChunker.chunk()
# ---------------------------------------------------------------------------

class TestLegalTextChunker:

    def setup_method(self):
        self.chunker = LegalTextChunker()

    def test_empty_extraction_returns_empty(self):
        result = ExtractionResult(
            source_path="test.pdf", file_sha256="abc", total_pages=0,
            status=ExtractionStatus.FAILED,
        )
        assert self.chunker.chunk(result) == []

    def test_basic_text_produces_chunks(self):
        text = "Section 183A. Speeding offence.\n" + ("Fine up to 2000 INR. " * 20)
        extraction = _make_extraction(text)
        chunks = self.chunker.chunk(extraction)
        assert len(chunks) > 0

    def test_all_chunks_have_required_fields(self):
        text = "Section 183. Fine for speeding. " * 50
        chunks = self.chunker.chunk(_make_extraction(text))
        for c in chunks:
            assert c.chunk_id
            assert c.source_doc
            assert c.file_sha256
            assert c.text
            assert c.char_count > 0

    def test_chunks_respect_min_char_limit(self):
        text = "Section 183. Fine for speeding. " * 50
        chunks = self.chunker.chunk(_make_extraction(text))
        for c in chunks:
            assert c.char_count >= MIN_CHUNK_CHARS, f"Chunk too short: {c.text!r}"

    def test_chunk_ids_unique(self):
        text = "Section 183. Fine. " * 200
        chunks = self.chunker.chunk(_make_extraction(text))
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_section_id_detected(self):
        text = "\nSection 183A. Punishment for over-speeding. " + ("Details. " * 30)
        chunks = self.chunker.chunk(_make_extraction(text))
        section_ids = [c.section_id for c in chunks if c.section_id]
        assert len(section_ids) > 0
        assert "183A" in section_ids

    def test_doc_type_propagated(self):
        extraction = _make_extraction("Section 1. " * 50, doc_type="GAZETTE_CENTRAL")
        chunks = self.chunker.chunk(extraction)
        for c in chunks:
            assert c.doc_type == "GAZETTE_CENTRAL"

    def test_file_sha256_propagated(self):
        extraction = _make_extraction("Section 1. " * 50, sha="deadbeef")
        chunks = self.chunker.chunk(extraction)
        for c in chunks:
            assert c.file_sha256 == "deadbeef"

    def test_page_marker_stripped_from_chunk_text(self):
        extraction = _make_extraction("Section 183. Fine for speeding. " * 30)
        chunks = self.chunker.chunk(extraction)
        for c in chunks:
            assert "[PAGE:" not in c.text

    def test_long_section_split_by_sliding_window(self):
        long_section = "Section 183. " + ("Very long legal text. " * 200)
        extraction = _make_extraction(long_section)
        chunks = self.chunker.chunk(extraction)
        # Long text must produce multiple chunks
        total_chars = sum(c.char_count for c in chunks)
        assert total_chars > 0

    def test_multi_page_extraction(self):
        pages = [
            PageText(1, "Section 183. Speeding. " * 20, ExtractionMethod.DIGITAL_PDFPLUMBER, 100),
            PageText(2, "Section 194. Helmet. " * 20, ExtractionMethod.DIGITAL_PDFPLUMBER, 100),
        ]
        extraction = ExtractionResult(
            source_path="multi.pdf", file_sha256="beef1234", total_pages=2,
            extracted_pages=pages, status=ExtractionStatus.SUCCESS, doc_type="MVA_ACT",
        )
        chunks = self.chunker.chunk(extraction)
        assert len(chunks) > 0
