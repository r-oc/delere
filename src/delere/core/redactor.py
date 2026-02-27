import logging
from pathlib import Path

import fitz

from delere.config import RedactionConfig
from delere.core.models import Detection, RedactionResult

logger = logging.getLogger(__name__)


class PDFRedactor:
    """Applies secure redactions to PDF documents.

    Security model:
    - Redaction annotations mark areas for removal.
    - apply_redactions() removes the actual content stream data, not just a visual overlay.
    - Metadata, XML metadata, and annotations are stripped.
    - The document is flattened and saved non-incrementally with garbage collection.
    - The original file is never modified.
    """

    def __init__(self, config: RedactionConfig) -> None:
        self._config = config

    def redact(
        self,
        input_path: Path,
        output_path: Path,
        detections: list[Detection],
        compliance_profiles: list[str],
        review_mode: bool = False,
    ) -> RedactionResult:
        """Apply redactions to a PDF and save the result.

        In review mode, adds redaction annotation overlays but does not
        apply them, so a human can inspect proposed redactions before
        finalizing. The text remains intact and extractable.
        """
        doc = fitz.open(str(input_path))
        page_count = doc.page_count

        self._add_redaction_annotations(doc, detections)

        if not review_mode:
            self._apply_redactions(doc)
            self._strip_metadata(doc)
            self._remove_annotations(doc)
            self._flatten(doc)

        self._save(doc, output_path)
        doc.close()

        return self._build_result(
            input_path, output_path, detections, page_count, compliance_profiles
        )

    def _add_redaction_annotations(
        self, doc: fitz.Document, detections: list[Detection]
    ) -> None:
        """Mark each detection's bounding boxes as redaction areas on the PDF."""
        for detection in detections:
            for bbox in detection.bounding_boxes:
                if bbox.page_number >= doc.page_count:
                    logger.warning(
                        "Skipping bbox on page %d (document has %d pages)",
                        bbox.page_number,
                        doc.page_count,
                    )
                    continue

                page = doc[bbox.page_number]
                rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
                page.add_redact_annot(rect, fill=self._config.fill_color)

    def _apply_redactions(self, doc: fitz.Document) -> None:
        """Apply all redaction annotations, removing content stream data.

        Uses the most aggressive removal flags:
        - PDF_REDACT_IMAGE_REMOVE: completely removes overlapping images
        - PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED: removes vector graphics that touch the area
        - PDF_REDACT_TEXT_REMOVE: removes text from the content stream
        """
        for page in doc:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_REMOVE,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )

    def _strip_metadata(self, doc: fitz.Document) -> None:
        """Remove all document-level metadata (Info dict and XMP)."""
        if not self._config.strip_metadata:
            return
        doc.set_metadata({})
        doc.del_xml_metadata()

    def _remove_annotations(self, doc: fitz.Document) -> None:
        """Remove all remaining annotations from every page.

        Uses the while-loop pattern with first_annot / delete_annot because
        pymupdf annotations form a linked list. Iterating with for-in and
        deleting inside the loop would skip entries after each deletion.
        """
        if not self._config.remove_annotations:
            return
        for page in doc:
            annot = page.first_annot
            while annot:
                annot = page.delete_annot(annot)

    def _flatten(self, doc: fitz.Document) -> None:
        """Flatten the document to bake any remaining form fields or annotations.

        This must happen AFTER apply_redactions(). Calling it before would
        bake redaction annotations as visual elements without actually
        removing the underlying text from the content stream.
        """
        if not self._config.flatten_after_redaction:
            return
        doc.bake(annots=True, widgets=True)

    def _save(self, doc: fitz.Document, output_path: Path) -> None:
        """Save with full garbage collection. Never uses incremental save.

        Incremental saves append to the file, leaving the original unredacted
        content stream physically present in the file bytes. Using garbage=4
        rewrites the entire file and deduplicates binary streams.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(
            str(output_path),
            garbage=4,
            deflate=True,
            clean=True,
        )

    def _build_result(
        self,
        input_path: Path,
        output_path: Path,
        detections: list[Detection],
        page_count: int,
        compliance_profiles: list[str],
    ) -> RedactionResult:
        by_category: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for d in detections:
            by_category[d.category.value] = by_category.get(d.category.value, 0) + 1
            by_source[d.source.value] = by_source.get(d.source.value, 0) + 1

        return RedactionResult(
            input_path=str(input_path),
            output_path=str(output_path),
            total_detections=len(detections),
            detections_by_category=by_category,
            detections_by_source=by_source,
            pages_processed=page_count,
            compliance_profiles=compliance_profiles,
        )
