from pathlib import Path

import fitz

from delere.core.models import PageText


def extract_text(pdf_path: Path) -> list[PageText]:
    """Extract text with word-level bounding boxes from every page of a PDF.

    Uses pymupdf's get_text("words") for positional data and get_text("text")
    for the full page string. The words list matches the tuple shape that
    the detection pipeline expects for bounding box lookups.
    """
    doc = fitz.open(str(pdf_path))
    pages: list[PageText] = []

    for page_num in range(doc.page_count):
        page = doc[page_num]
        words_raw = page.get_text("words")

        # pymupdf returns a list of tuples:
        # (x0, y0, x1, y1, "word", block_no, line_no, word_no)
        words = [
            (float(w[0]), float(w[1]), float(w[2]), float(w[3]), w[4], w[5], w[6], w[7])
            for w in words_raw
        ]

        pages.append(PageText(
            page_number=page_num,
            full_text=page.get_text("text"),
            words=words,
        ))

    doc.close()
    return pages
