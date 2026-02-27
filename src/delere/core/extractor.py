import logging
from pathlib import Path

import fitz

from delere.config import OcrConfig
from delere.core.models import PageText

logger = logging.getLogger(__name__)


def _is_image_only_page(page: fitz.Page, min_text_threshold: int) -> bool:
    """Determine if a page contains only images and no meaningful embedded text.

    A page is considered image-only if it has at least one image and the
    extracted text content is below the minimum threshold.
    """
    text = page.get_text("text").strip()
    if len(text) >= min_text_threshold:
        return False
    image_list = page.get_images(full=True)
    return len(image_list) > 0


def _extract_page_native(page: fitz.Page, page_num: int) -> PageText:
    """Extract text from a page using PyMuPDF's native text extraction."""
    words_raw = page.get_text("words")
    words = [
        (float(w[0]), float(w[1]), float(w[2]), float(w[3]), w[4], w[5], w[6], w[7])
        for w in words_raw
    ]
    return PageText(
        page_number=page_num,
        full_text=page.get_text("text"),
        words=words,
    )


def _extract_page_ocr(
    page: fitz.Page, page_num: int, language: str, dpi: int
) -> PageText:
    """Extract text from a page using Tesseract OCR via PyMuPDF.

    Uses page.get_textpage_ocr() which renders the page at the given DPI,
    runs Tesseract, and returns a TextPage with the same API as native
    extraction. Bounding boxes are in the same coordinate space.
    """
    tp = page.get_textpage_ocr(
        flags=fitz.TEXT_PRESERVE_WHITESPACE,
        language=language,
        dpi=dpi,
        full=True,
    )

    words_raw = page.get_text("words", textpage=tp)
    words = [
        (float(w[0]), float(w[1]), float(w[2]), float(w[3]), w[4], w[5], w[6], w[7])
        for w in words_raw
    ]

    return PageText(
        page_number=page_num,
        full_text=page.get_text("text", textpage=tp),
        words=words,
        is_ocr=True,
    )


def is_ocr_available() -> bool:
    """Check if Tesseract is installed and accessible to PyMuPDF."""
    try:
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.get_textpage_ocr(dpi=72)
        doc.close()
        return True
    except Exception:
        return False


def extract_text(
    pdf_path: Path, ocr_config: OcrConfig | None = None
) -> list[PageText]:
    """Extract text with word-level bounding boxes from every page of a PDF.

    When OCR is enabled, pages that appear to be image-only (scanned documents)
    are automatically processed with Tesseract OCR via PyMuPDF. Pages with
    existing text layers use native extraction for speed and accuracy.
    """
    doc = fitz.open(str(pdf_path))
    pages: list[PageText] = []

    for page_num in range(doc.page_count):
        page = doc[page_num]

        use_ocr = (
            ocr_config is not None
            and ocr_config.enabled
            and _is_image_only_page(page, ocr_config.min_text_threshold)
        )

        if use_ocr:
            assert ocr_config is not None
            logger.info("Page %d: using OCR (image-only page detected)", page_num)
            pages.append(
                _extract_page_ocr(page, page_num, ocr_config.language, ocr_config.dpi)
            )
        else:
            pages.append(_extract_page_native(page, page_num))

    doc.close()
    return pages
