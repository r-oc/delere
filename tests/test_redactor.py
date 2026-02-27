from pathlib import Path

import fitz
import pytest

from delere.config import AppConfig, RedactionConfig
from delere.core.extractor import extract_text
from delere.core.models import BoundingBox, Detection, DetectorSource, PIICategory
from delere.core.pipeline import DetectionPipeline
from delere.core.redactor import PDFRedactor
from delere.detectors.regex import RegexDetector
from delere.profiles.loader import load_profile


@pytest.fixture
def sample_pdf_with_pii(tmp_path: Path) -> Path:
    """Generate a test PDF containing known PII for redaction testing."""
    doc = fitz.open()
    page = doc.new_page()

    lines = [
        "Patient: Sarah Thompson",
        "SIN: 123-456-789",
        "Email: sarah.thompson@example.com",
        "Phone: (416) 555-0123",
        "Address: 123 Maple Street, Toronto, ON M5V 2T6",
        "",
        "This document contains sensitive information.",
    ]

    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 20

    # Add some metadata to verify it gets stripped
    doc.set_metadata({
        "author": "Test Author",
        "title": "Confidential Patient Record",
        "subject": "Medical",
    })

    path = tmp_path / "sample_pii.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def redactor() -> PDFRedactor:
    return PDFRedactor(RedactionConfig())


def _run_full_pipeline(pdf_path: Path) -> list[Detection]:
    """Run the regex detector on a real PDF and return detections."""
    profile = load_profile("pipeda")
    detector = RegexDetector(profile)
    config = AppConfig(confidence_threshold=0.0)
    pipeline = DetectionPipeline([detector], config)
    page_texts = extract_text(pdf_path)
    return pipeline.run(page_texts)


class TestSecureRedaction:
    def test_pii_text_removed_from_content_stream(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """After redaction, PII text should not be extractable from the output PDF."""
        detections = _run_full_pipeline(sample_pdf_with_pii)
        assert len(detections) > 0, "Pipeline should find PII in the sample"

        output = tmp_path / "redacted.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        # Verify PII is gone from the content stream
        doc = fitz.open(str(output))
        full_text = "".join(page.get_text() for page in doc)
        doc.close()

        assert "sarah.thompson@example.com" not in full_text.lower()

    def test_non_pii_text_survives(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """Text that is not PII should remain in the redacted output."""
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "redacted.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        doc = fitz.open(str(output))
        full_text = "".join(page.get_text() for page in doc)
        doc.close()

        assert "sensitive information" in full_text.lower()

    def test_metadata_stripped(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """Output PDF should have empty metadata."""
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "redacted.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        doc = fitz.open(str(output))
        metadata = doc.metadata
        doc.close()

        assert metadata.get("author", "") == ""
        assert metadata.get("title", "") == ""
        assert metadata.get("subject", "") == ""

    def test_xml_metadata_stripped(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """Output PDF should have no XMP metadata."""
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "redacted.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        doc = fitz.open(str(output))
        xmp = doc.get_xml_metadata()
        doc.close()

        assert xmp == ""

    def test_no_annotations_remain(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """Output PDF should have no annotations after redaction."""
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "redacted.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        doc = fitz.open(str(output))
        for page in doc:
            assert page.first_annot is None
        doc.close()


class TestReviewMode:
    def test_review_mode_preserves_text(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """In review mode, text is NOT removed. Annotations are added for review."""
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "review.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"], review_mode=True
        )

        doc = fitz.open(str(output))
        full_text = "".join(page.get_text() for page in doc)
        doc.close()

        # Text should still be present since we only added annotations
        assert "sarah.thompson@example.com" in full_text.lower()

    def test_review_mode_keeps_metadata(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        """Review mode should not strip metadata."""
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "review.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"], review_mode=True
        )

        doc = fitz.open(str(output))
        metadata = doc.metadata
        doc.close()

        assert metadata.get("author") == "Test Author"


class TestRedactionResult:
    def test_result_counts(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "redacted.pdf"
        result = redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        assert result.total_detections == len(detections)
        assert result.pages_processed == 1
        assert result.compliance_profiles == ["pipeda"]
        assert sum(result.detections_by_category.values()) == len(detections)

    def test_output_file_created(
        self, sample_pdf_with_pii: Path, tmp_path: Path, redactor: PDFRedactor
    ):
        detections = _run_full_pipeline(sample_pdf_with_pii)

        output = tmp_path / "subdir" / "redacted.pdf"
        redactor.redact(
            sample_pdf_with_pii, output, detections, ["pipeda"]
        )

        assert output.exists()
        assert output.stat().st_size > 0


class TestTextExtraction:
    def test_extract_text_returns_pages(self, sample_pdf_with_pii: Path):
        pages = extract_text(sample_pdf_with_pii)
        assert len(pages) == 1
        assert pages[0].page_number == 0
        assert len(pages[0].words) > 0
        assert "sarah" in pages[0].full_text.lower()

    def test_word_tuples_have_correct_shape(self, sample_pdf_with_pii: Path):
        pages = extract_text(sample_pdf_with_pii)
        for word in pages[0].words:
            assert len(word) == 8
            # x0, y0, x1, y1 are floats
            assert isinstance(word[0], float)
            assert isinstance(word[1], float)
            # word text is a string
            assert isinstance(word[4], str)
