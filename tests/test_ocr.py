from pathlib import Path

import fitz
import pytest

from delere.config import OcrConfig, RedactionConfig
from delere.core.extractor import _is_image_only_page, extract_text, is_ocr_available
from delere.core.models import BoundingBox, Detection, DetectorSource, PIICategory
from delere.core.redactor import PDFRedactor

_tesseract_available = is_ocr_available()
requires_tesseract = pytest.mark.skipif(
    not _tesseract_available, reason="Tesseract not installed"
)


def _create_text_pdf(tmp_path: Path, text: str = "Hello World") -> Path:
    """Create a PDF with embedded text (not scanned)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=14)
    path = tmp_path / "text.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _create_scanned_pdf(
    tmp_path: Path, text: str = "John Smith 123-456-789"
) -> Path:
    """Create a PDF that simulates a scanned document.

    Renders text to a pixmap and inserts it as an image, resulting in a
    page with image content but no text layer.
    """
    # Render text to an image
    tmp_doc = fitz.open()
    tmp_page = tmp_doc.new_page()
    tmp_page.insert_text((72, 100), text, fontsize=14)
    pix = tmp_page.get_pixmap(dpi=300)
    tmp_doc.close()

    # Insert the rendered image into a new PDF (no text layer)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "scanned.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _create_blank_pdf(tmp_path: Path) -> Path:
    """Create a blank PDF with no images and no text."""
    doc = fitz.open()
    doc.new_page()
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    doc.close()
    return path


class TestImageOnlyDetection:
    def test_text_page_not_detected_as_image_only(self, tmp_path: Path):
        """A page with normal text content should not trigger OCR."""
        path = _create_text_pdf(tmp_path)
        doc = fitz.open(str(path))
        assert not _is_image_only_page(doc[0], min_text_threshold=10)
        doc.close()

    def test_image_only_page_detected(self, tmp_path: Path):
        """A page with only an image and no text should trigger OCR."""
        path = _create_scanned_pdf(tmp_path)
        doc = fitz.open(str(path))
        assert _is_image_only_page(doc[0], min_text_threshold=10)
        doc.close()

    def test_blank_page_not_image_only(self, tmp_path: Path):
        """A blank page (no images, no text) should not trigger OCR."""
        path = _create_blank_pdf(tmp_path)
        doc = fitz.open(str(path))
        assert not _is_image_only_page(doc[0], min_text_threshold=10)
        doc.close()

    def test_min_text_threshold_configurable(self, tmp_path: Path):
        """Pages with text below a custom threshold should trigger OCR."""
        # Create a page with a short text and an image
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Hi", fontsize=12)  # 2 chars
        # Add a dummy image
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), 1)
        page.insert_image(fitz.Rect(200, 200, 300, 300), pixmap=pix)
        path = tmp_path / "short_text.pdf"
        doc.save(str(path))
        doc.close()

        doc = fitz.open(str(path))
        page = doc[0]
        # Threshold 10: "Hi" (2 chars) is below -> image-only
        assert _is_image_only_page(page, min_text_threshold=10)
        # Threshold 1: "Hi" (2 chars) is above -> not image-only
        assert not _is_image_only_page(page, min_text_threshold=2)
        doc.close()


class TestExtractTextBackwardCompat:
    def test_extract_text_without_ocr_config(self, tmp_path: Path):
        """extract_text() with no ocr_config should work exactly as before."""
        path = _create_text_pdf(tmp_path, "Test backward compatibility")
        pages = extract_text(path)
        assert len(pages) == 1
        assert "backward" in pages[0].full_text.lower()
        assert pages[0].is_ocr is False

    def test_native_page_not_marked_as_ocr(self, tmp_path: Path):
        """Native text pages should have is_ocr=False."""
        path = _create_text_pdf(tmp_path)
        pages = extract_text(path)
        assert pages[0].is_ocr is False

    def test_page_text_default_is_ocr_false(self):
        """PageText constructed without is_ocr should default to False."""
        from delere.core.models import PageText

        pt = PageText(page_number=0, full_text="test", words=[])
        assert pt.is_ocr is False


@requires_tesseract
class TestOcrExtraction:
    def test_ocr_extracts_text_from_image_pdf(self, tmp_path: Path):
        """OCR should extract readable text from a scanned page."""
        path = _create_scanned_pdf(tmp_path, "John Smith 123-456-789")
        ocr_config = OcrConfig(enabled=True, dpi=300)
        pages = extract_text(path, ocr_config=ocr_config)

        assert len(pages) == 1
        # OCR should find at least some of the text
        text_lower = pages[0].full_text.lower()
        assert "john" in text_lower or "smith" in text_lower

    def test_ocr_produces_valid_page_text_shape(self, tmp_path: Path):
        """OCR output should match the PageText word tuple format."""
        path = _create_scanned_pdf(tmp_path)
        ocr_config = OcrConfig(enabled=True, dpi=300)
        pages = extract_text(path, ocr_config=ocr_config)

        assert len(pages) == 1
        assert len(pages[0].words) > 0
        for word in pages[0].words:
            assert len(word) == 8
            assert isinstance(word[0], float)
            assert isinstance(word[1], float)
            assert isinstance(word[2], float)
            assert isinstance(word[3], float)
            assert isinstance(word[4], str)

    def test_ocr_page_marked_as_ocr(self, tmp_path: Path):
        """Pages processed with OCR should have is_ocr=True."""
        path = _create_scanned_pdf(tmp_path)
        ocr_config = OcrConfig(enabled=True, dpi=300)
        pages = extract_text(path, ocr_config=ocr_config)

        assert pages[0].is_ocr is True

    def test_mixed_document_selective_ocr(self, tmp_path: Path):
        """Only image-only pages should be OCR'd in a mixed document."""
        # Create a 2-page PDF: page 0 = text, page 1 = image-only
        doc = fitz.open()

        # Page 0: native text
        page0 = doc.new_page()
        page0.insert_text((72, 100), "This is a native text page with enough content", fontsize=12)

        # Page 1: scanned image
        tmp_doc = fitz.open()
        tmp_page = tmp_doc.new_page()
        tmp_page.insert_text((72, 100), "Scanned content here", fontsize=14)
        pix = tmp_page.get_pixmap(dpi=300)
        tmp_doc.close()

        page1 = doc.new_page()
        page1.insert_image(page1.rect, pixmap=pix)

        path = tmp_path / "mixed.pdf"
        doc.save(str(path))
        doc.close()

        ocr_config = OcrConfig(enabled=True, dpi=300)
        pages = extract_text(path, ocr_config=ocr_config)

        assert len(pages) == 2
        assert pages[0].is_ocr is False  # native text page
        assert pages[1].is_ocr is True   # image-only page


@requires_tesseract
class TestOcrRedaction:
    def test_image_page_not_destroyed(self, tmp_path: Path):
        """Redacting PII on an OCR page should not remove the entire page image."""
        path = _create_scanned_pdf(tmp_path, "John Smith 123-456-789")

        # Extract with OCR
        ocr_config = OcrConfig(enabled=True, dpi=300)
        pages = extract_text(path, ocr_config=ocr_config)
        ocr_pages = frozenset(pt.page_number for pt in pages if pt.is_ocr)

        # Create a detection with a small bounding box
        detections = [
            Detection(
                text="123-456-789",
                category=PIICategory.SIN,
                source=DetectorSource.REGEX,
                confidence=0.95,
                bounding_boxes=[BoundingBox(x0=100, y0=90, x1=250, y1=110, page_number=0)],
            )
        ]

        output = tmp_path / "redacted.pdf"
        redactor = PDFRedactor(RedactionConfig())
        redactor.redact(path, output, detections, ["pipeda"], ocr_pages=ocr_pages)

        # The output should exist and the page should still have image content
        assert output.exists()
        doc = fitz.open(str(output))
        page = doc[0]
        images = page.get_images(full=True)
        # The page image should still exist (not removed)
        assert len(images) > 0
        doc.close()

    def test_native_page_still_uses_image_remove(self, tmp_path: Path):
        """Non-OCR pages should still use the aggressive IMAGE_REMOVE flag."""
        # This test verifies backward compat: redact() without ocr_pages works
        path = _create_text_pdf(tmp_path, "test@example.com")
        detections = [
            Detection(
                text="test@example.com",
                category=PIICategory.EMAIL,
                source=DetectorSource.REGEX,
                confidence=0.95,
                bounding_boxes=[BoundingBox(x0=72, y0=90, x1=250, y1=110, page_number=0)],
            )
        ]

        output = tmp_path / "redacted.pdf"
        redactor = PDFRedactor(RedactionConfig())
        # No ocr_pages -> all pages use aggressive flags
        redactor.redact(path, output, detections, ["pipeda"])
        assert output.exists()
