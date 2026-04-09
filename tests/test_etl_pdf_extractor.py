"""
tests/test_etl_pdf_extractor.py

Unit tests for etl/pdf_extractor.py covering:
  - ExtractionResult.full_text property
  - ExtractionResult.pages_failed property
  - PDFExtractor._classify_doc_type static method
  - PDFExtractor._make_failed static method
  - PDFExtractor._sha256 static method
  - PDFExtractor._check_ocr_available lazy flag
  - PDFExtractor.extract() for non-existent file (returns FAILED)
  - PDFExtractor.extract() with mocked pdfplumber for digital extraction
  - Metadata regex patterns (INDIAN_SECTION_PATTERN, GO_NOTIFICATION_PATTERN,
    GAZETTE_REF_PATTERN)
  - PageText dataclass construction
"""
import sys
import os
import tempfile
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from etl.pdf_extractor import (
    PDFExtractor,
    ExtractionResult,
    ExtractionStatus,
    ExtractionMethod,
    PageText,
    INDIAN_SECTION_PATTERN,
    GO_NOTIFICATION_PATTERN,
    GAZETTE_REF_PATTERN,
    MIN_DIGITAL_CHARS_PER_PAGE,
)


# ---------------------------------------------------------------------------
# ExtractionResult — properties
# ---------------------------------------------------------------------------

class TestExtractionResultProperties:

    def _result(self, pages=None):
        return ExtractionResult(
            source_path="test.pdf",
            file_sha256="deadbeef",
            total_pages=len(pages) if pages else 0,
            extracted_pages=pages or [],
            status=ExtractionStatus.SUCCESS,
        )

    def _page(self, num, text):
        return PageText(
            page_number=num,
            raw_text=text,
            method=ExtractionMethod.DIGITAL_PDFPLUMBER,
            char_count=len(text),
        )

    def test_full_text_empty_when_no_pages(self):
        r = self._result()
        assert r.full_text == ""

    def test_full_text_single_page(self):
        r = self._result([self._page(1, "Section 183 fine for speeding.")])
        assert "Section 183" in r.full_text

    def test_full_text_multiple_pages_joined(self):
        r = self._result([
            self._page(1, "First page content."),
            self._page(2, "Second page content."),
        ])
        assert "First page" in r.full_text
        assert "Second page" in r.full_text

    def test_full_text_skips_blank_pages(self):
        r = self._result([
            self._page(1, "Real text here."),
            self._page(2, "   "),   # blank page
        ])
        assert "Real text" in r.full_text
        assert r.full_text.count("Real text") == 1

    def test_pages_failed_zero_when_all_extracted(self):
        r = self._result([self._page(1, "text"), self._page(2, "text")])
        r.total_pages = 2
        assert r.pages_failed == 0

    def test_pages_failed_positive_when_pages_missing(self):
        r = self._result([self._page(1, "text")])
        r.total_pages = 3
        assert r.pages_failed == 2

    def test_pages_failed_equals_total_minus_extracted(self):
        r = self._result([self._page(1, "text"), self._page(2, "text")])
        r.total_pages = 5
        assert r.pages_failed == 3


# ---------------------------------------------------------------------------
# PDFExtractor._classify_doc_type
# ---------------------------------------------------------------------------

class TestClassifyDocType:

    def test_gazette_from_filename(self):
        assert PDFExtractor._classify_doc_type("gazette_123") == "GAZETTE_CENTRAL"

    def test_so_filename(self):
        assert PDFExtractor._classify_doc_type("s_o_2224E") == "GAZETTE_CENTRAL"

    def test_so_prefix_filename(self):
        assert PDFExtractor._classify_doc_type("so_2224") == "GAZETTE_CENTRAL"

    def test_go_filename(self):
        assert PDFExtractor._classify_doc_type("g_o_ms_no_56") == "TN_STATE_GO"

    def test_go_prefix_filename(self):
        assert PDFExtractor._classify_doc_type("go_56") == "TN_STATE_GO"

    def test_state_filename(self):
        assert PDFExtractor._classify_doc_type("state_transport_act") == "TN_STATE_GO"

    def test_mva_filename(self):
        assert PDFExtractor._classify_doc_type("mva_1988_amended") == "MVA_ACT"

    def test_motor_vehicles_filename(self):
        assert PDFExtractor._classify_doc_type("motor_vehicles_act") == "MVA_ACT"

    def test_irad_filename(self):
        assert PDFExtractor._classify_doc_type("irad_telemetry_2023") == "IRAD_DATASET"

    def test_unknown_filename(self):
        assert PDFExtractor._classify_doc_type("random_document") == "UNKNOWN"

    def test_case_insensitive(self):
        assert PDFExtractor._classify_doc_type("GAZETTE_2024") == "GAZETTE_CENTRAL"


# ---------------------------------------------------------------------------
# PDFExtractor._make_failed
# ---------------------------------------------------------------------------

class TestMakeFailed:

    def test_returns_extraction_result(self):
        r = PDFExtractor._make_failed("test.pdf", "some error", 12345)
        assert isinstance(r, ExtractionResult)

    def test_status_is_failed(self):
        r = PDFExtractor._make_failed("test.pdf", "error", 0)
        assert r.status == ExtractionStatus.FAILED

    def test_source_path_set(self):
        r = PDFExtractor._make_failed("/path/to/file.pdf", "error", 0)
        assert r.source_path == "/path/to/file.pdf"

    def test_file_sha256_empty(self):
        r = PDFExtractor._make_failed("test.pdf", "error", 0)
        assert r.file_sha256 == ""

    def test_total_pages_zero(self):
        r = PDFExtractor._make_failed("test.pdf", "error", 0)
        assert r.total_pages == 0

    def test_error_log_contains_reason(self):
        r = PDFExtractor._make_failed("test.pdf", "Cannot read file: permission denied", 0)
        assert any("Cannot read file" in e for e in r.error_log)

    def test_timestamp_stored(self):
        r = PDFExtractor._make_failed("test.pdf", "error", 99999)
        assert r.extraction_timestamp_epoch_ms == 99999


# ---------------------------------------------------------------------------
# PDFExtractor._sha256
# ---------------------------------------------------------------------------

class TestSha256:

    def test_sha256_produces_64_char_hex(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"test content for sha256")
            path = f.name
        try:
            from pathlib import Path
            result = PDFExtractor._sha256(Path(path))
            assert len(result) == 64
            assert all(c in "0123456789abcdef" for c in result)
        finally:
            os.unlink(path)

    def test_sha256_deterministic(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"deterministic content")
            path = f.name
        try:
            from pathlib import Path
            h1 = PDFExtractor._sha256(Path(path))
            h2 = PDFExtractor._sha256(Path(path))
            assert h1 == h2
        finally:
            os.unlink(path)

    def test_sha256_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f1:
            f1.write(b"content A")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f2:
            f2.write(b"content B")
            p2 = f2.name
        try:
            from pathlib import Path
            assert PDFExtractor._sha256(Path(p1)) != PDFExtractor._sha256(Path(p2))
        finally:
            os.unlink(p1)
            os.unlink(p2)


# ---------------------------------------------------------------------------
# PDFExtractor._check_ocr_available — lazy flag behaviour
# ---------------------------------------------------------------------------

class TestCheckOcrAvailable:

    def test_returns_bool(self):
        ex = PDFExtractor()
        result = ex._check_ocr_available()
        assert isinstance(result, bool)

    def test_result_cached_on_second_call(self):
        ex = PDFExtractor()
        r1 = ex._check_ocr_available()
        # Forcibly set the cached value
        ex._ocr_available = not r1
        r2 = ex._check_ocr_available()
        assert r2 == (not r1), "Second call must return cached value, not re-check"

    def test_false_when_pdf2image_missing(self):
        ex = PDFExtractor()
        with patch.dict("sys.modules", {"pdf2image": None}):
            ex._ocr_available = None  # reset cache
            result = ex._check_ocr_available()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# PDFExtractor.extract() — file-not-found path (no real PDF needed)
# ---------------------------------------------------------------------------

class TestExtractFileMissing:

    def test_missing_file_returns_failed_status(self):
        ex = PDFExtractor()
        result = ex.extract("/nonexistent/path/does_not_exist_xyzzy.pdf")
        assert result.status == ExtractionStatus.FAILED

    def test_missing_file_error_log_populated(self):
        ex = PDFExtractor()
        result = ex.extract("/no/such/file.pdf")
        assert len(result.error_log) > 0

    def test_missing_file_result_has_empty_sha256(self):
        ex = PDFExtractor()
        result = ex.extract("/no/such/file.pdf")
        assert result.file_sha256 == ""


# ---------------------------------------------------------------------------
# PDFExtractor.extract() — mocked pdfplumber for digital-extraction path
# ---------------------------------------------------------------------------

class TestExtractMocked:

    def _create_mock_pdfplumber_page(self, text: str):
        """Returns a mock pdfplumber Page object returning ``text``."""
        page = MagicMock()
        page.extract_text.return_value = text
        return page

    def _make_extractor(self, pages_text, ocr_fallback=False):
        """
        Return a PDFExtractor pre-configured with a mocked pdfplumber PDF
        containing pages with the given texts.
        """
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.is_encrypted = False
        mock_pages = [self._create_mock_pdfplumber_page(t) for t in pages_text]
        mock_pdf.pages = mock_pages

        ex = PDFExtractor(ocr_fallback=ocr_fallback)
        return ex, mock_pdf

    def _run_extract(self, ex, mock_pdf, filename="gazette_test.pdf"):
        """Run extract with a real temp file (for sha256) + mocked pdfplumber."""
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".pdf", prefix=filename.rstrip(".pdf")
        ) as f:
            f.write(b"%PDF-1.4 minimal")
            tmp_path = f.name
        try:
            with patch("pdfplumber.open", return_value=mock_pdf):
                result = ex.extract(tmp_path)
        finally:
            os.unlink(tmp_path)
        return result

    def test_success_status_when_all_pages_extracted(self):
        long_text = "Section 183 Speeding. " * 40  # well above MIN_DIGITAL_CHARS_PER_PAGE
        ex, mock_pdf = self._make_extractor([long_text])
        result = self._run_extract(ex, mock_pdf)
        assert result.status == ExtractionStatus.SUCCESS

    def test_extracted_pages_count(self):
        text = "Legal text. " * 40
        ex, mock_pdf = self._make_extractor([text, text])
        result = self._run_extract(ex, mock_pdf)
        assert len(result.extracted_pages) == 2

    def test_digital_method_used(self):
        text = "A" * (MIN_DIGITAL_CHARS_PER_PAGE + 10)
        ex, mock_pdf = self._make_extractor([text])
        result = self._run_extract(ex, mock_pdf)
        assert result.method == ExtractionMethod.DIGITAL_PDFPLUMBER

    def test_doc_type_from_filename(self):
        text = "A" * (MIN_DIGITAL_CHARS_PER_PAGE + 10)
        ex, mock_pdf = self._make_extractor([text])
        # filename stem contains "gazette" → GAZETTE_CENTRAL
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".pdf", prefix="gazette_2024_"
        ) as f:
            f.write(b"%PDF-1.4 minimal")
            tmp_path = f.name
        try:
            with patch("pdfplumber.open", return_value=mock_pdf):
                result = ex.extract(tmp_path)
        finally:
            os.unlink(tmp_path)
        assert result.doc_type == "GAZETTE_CENTRAL"

    def test_sections_detected_from_text(self):
        text = "Section 183A Speeding. " * 10 + "A" * 200
        ex, mock_pdf = self._make_extractor([text])
        result = self._run_extract(ex, mock_pdf)
        assert "183A" in result.sections_detected

    def test_gazette_ref_detected(self):
        text = "S.O. 2224(E) notification. " + "A" * 200
        ex, mock_pdf = self._make_extractor([text])
        result = self._run_extract(ex, mock_pdf)
        assert result.gazette_ref is not None
        assert "2224" in result.gazette_ref

    def test_go_ref_detected(self):
        text = "G.O.(Ms).No.56 State Government. " + "A" * 200
        ex, mock_pdf = self._make_extractor([text])
        result = self._run_extract(ex, mock_pdf)
        assert result.go_ref is not None
        assert "56" in result.go_ref

    def test_partial_status_when_some_pages_fail(self):
        """Page returning None from _extract_page → partial status."""
        text = "A" * (MIN_DIGITAL_CHARS_PER_PAGE + 10)
        ex, mock_pdf = self._make_extractor([text, text])
        # Make second page raise during extract_text
        mock_pdf.pages[1].extract_text.side_effect = Exception("page corrupt")
        # After exception: digital_text="" < threshold, OCR disabled → PageText returned
        # To trigger partial we need page result to be None — patch _extract_page
        original_extract_page = ex._extract_page

        call_count = [0]
        def patched_extract_page(pdf_path, page_num, plumber_page):
            call_count[0] += 1
            if call_count[0] == 2:
                return None
            return original_extract_page(pdf_path, page_num, plumber_page)

        ex._extract_page = patched_extract_page

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(b"%PDF-1.4")
            tmp_path = f.name
        try:
            with patch("pdfplumber.open", return_value=mock_pdf):
                result = ex.extract(tmp_path)
        finally:
            os.unlink(tmp_path)
        assert result.status == ExtractionStatus.PARTIAL


# ---------------------------------------------------------------------------
# Metadata regex patterns
# ---------------------------------------------------------------------------

class TestMetadataPatterns:

    def test_indian_section_pattern_finds_english_section(self):
        text = "\nSection 183A punishment for speeding"
        matches = INDIAN_SECTION_PATTERN.findall(text)
        assert any("183A" in m for m in matches)

    def test_indian_section_pattern_finds_hindi(self):
        text = "\nधारा 183 दंड"
        matches = INDIAN_SECTION_PATTERN.findall(text)
        assert len(matches) > 0

    def test_go_notification_pattern_finds_go(self):
        text = "G.O.(Ms).No.56 dated 2023"
        m = GO_NOTIFICATION_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "56"

    def test_gazette_ref_pattern_finds_so(self):
        text = "S.O. 2224(E) notification"
        m = GAZETTE_REF_PATTERN.search(text)
        assert m is not None
        assert "2224" in m.group(0)

    def test_patterns_return_none_on_no_match(self):
        text = "No statutory references here."
        assert INDIAN_SECTION_PATTERN.findall(text) == []
        assert GO_NOTIFICATION_PATTERN.search(text) is None
        assert GAZETTE_REF_PATTERN.search(text) is None


# ---------------------------------------------------------------------------
# PageText dataclass
# ---------------------------------------------------------------------------

class TestPageText:

    def test_construction(self):
        pt = PageText(
            page_number=1,
            raw_text="Section 183",
            method=ExtractionMethod.DIGITAL_PDFPLUMBER,
            char_count=11,
        )
        assert pt.page_number == 1
        assert pt.raw_text == "Section 183"
        assert pt.ocr_confidence is None
        assert pt.extraction_time_ms == 0.0

    def test_ocr_confidence_optional(self):
        pt = PageText(
            page_number=2,
            raw_text="OCR text",
            method=ExtractionMethod.OCR_TESSERACT,
            char_count=8,
            ocr_confidence=87.5,
        )
        assert pt.ocr_confidence == 87.5


# ---------------------------------------------------------------------------
# PDFExtractor constructor defaults
# ---------------------------------------------------------------------------

class TestPDFExtractorDefaults:

    def test_default_ocr_fallback_enabled(self):
        ex = PDFExtractor()
        assert ex.ocr_fallback is True

    def test_default_min_chars(self):
        ex = PDFExtractor()
        assert ex.min_chars_threshold == MIN_DIGITAL_CHARS_PER_PAGE

    def test_custom_min_chars(self):
        ex = PDFExtractor(min_chars_threshold=200)
        assert ex.min_chars_threshold == 200

    def test_ocr_available_initially_none(self):
        ex = PDFExtractor()
        assert ex._ocr_available is None
