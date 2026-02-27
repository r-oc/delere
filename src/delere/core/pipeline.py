from delere.config import AppConfig
from delere.core.models import Detection, PageText
from delere.detectors.base import BaseDetector


class DetectionPipeline:
    """Runs all configured detectors and merges their results.

    Assembles the full document text once, passes it to each available
    detector, applies the confidence threshold, and deduplicates
    overlapping detections from different layers.
    """

    def __init__(self, detectors: list[BaseDetector], config: AppConfig) -> None:
        self._detectors = detectors
        self._threshold = config.confidence_threshold

    # Single characters and very short strings are never meaningful PII.
    # This prevents false positives like "4" from "Bankruptcies: 4".
    MIN_DETECTION_LENGTH = 2

    def run(self, page_texts: list[PageText]) -> list[Detection]:
        full_text = "\n".join(pt.full_text for pt in page_texts)

        all_detections: list[Detection] = []
        for detector in self._detectors:
            if not detector.is_available():
                continue
            all_detections.extend(detector.detect(page_texts, full_text))

        filtered = [
            d for d in all_detections
            if d.confidence >= self._threshold
            and len(d.text.strip()) >= self.MIN_DETECTION_LENGTH
        ]
        return self._deduplicate(filtered)

    def _deduplicate(self, detections: list[Detection]) -> list[Detection]:
        """Remove duplicate detections of the same text at the same location.

        Groups detections by their normalized text and the page number of their
        first bounding box. Within each group, keeps the detection with the
        highest confidence score.
        """
        groups: dict[tuple[str, int], Detection] = {}

        for det in detections:
            page = det.bounding_boxes[0].page_number if det.bounding_boxes else -1
            key = (det.text.lower().strip(), page)

            existing = groups.get(key)
            if existing is None or det.confidence > existing.confidence:
                groups[key] = det

        return list(groups.values())
