from delere.config import AppConfig
from delere.core.models import (
    BoundingBox,
    Detection,
    DetectorSource,
    PIICategory,
    PageText,
)
from delere.core.pipeline import DetectionPipeline
from delere.detectors.base import BaseDetector


class FakeDetector(BaseDetector):
    """Test double that returns preconfigured detections."""

    def __init__(
        self, detections: list[Detection], available: bool = True
    ) -> None:
        self._detections = detections
        self._available = available

    def detect(self, page_texts: list[PageText], full_text: str) -> list[Detection]:
        return self._detections

    def is_available(self) -> bool:
        return self._available


def _bbox(page: int = 0) -> BoundingBox:
    return BoundingBox(x0=0, y0=0, x1=100, y1=12, page_number=page)


def _detection(
    text: str = "test@example.com",
    category: PIICategory = PIICategory.EMAIL,
    source: DetectorSource = DetectorSource.REGEX,
    confidence: float = 0.9,
    page: int = 0,
) -> Detection:
    return Detection(
        text=text,
        category=category,
        source=source,
        confidence=confidence,
        bounding_boxes=[_bbox(page)],
    )


class TestPipelineDeduplication:
    def test_same_text_same_page_keeps_highest_confidence(self):
        regex_det = _detection(source=DetectorSource.REGEX, confidence=0.95)
        spacy_det = _detection(source=DetectorSource.SPACY, confidence=0.80)

        pipeline = DetectionPipeline(
            [FakeDetector([regex_det]), FakeDetector([spacy_det])],
            AppConfig(confidence_threshold=0.0),
        )
        results = pipeline.run([])

        assert len(results) == 1
        assert results[0].confidence == 0.95
        assert results[0].source == DetectorSource.REGEX

    def test_different_text_not_deduplicated(self):
        det1 = _detection(text="test@example.com")
        det2 = _detection(text="other@example.com")

        pipeline = DetectionPipeline(
            [FakeDetector([det1, det2])],
            AppConfig(confidence_threshold=0.0),
        )
        results = pipeline.run([])
        assert len(results) == 2

    def test_same_text_different_pages_not_deduplicated(self):
        det1 = _detection(text="John Smith", page=0)
        det2 = _detection(text="John Smith", page=1)

        pipeline = DetectionPipeline(
            [FakeDetector([det1, det2])],
            AppConfig(confidence_threshold=0.0),
        )
        results = pipeline.run([])
        assert len(results) == 2


class TestPipelineFiltering:
    def test_below_threshold_filtered(self):
        low = _detection(confidence=0.3)
        high = _detection(text="other@example.com", confidence=0.9)

        pipeline = DetectionPipeline(
            [FakeDetector([low, high])],
            AppConfig(confidence_threshold=0.5),
        )
        results = pipeline.run([])

        assert len(results) == 1
        assert results[0].text == "other@example.com"

    def test_at_threshold_included(self):
        det = _detection(confidence=0.6)

        pipeline = DetectionPipeline(
            [FakeDetector([det])],
            AppConfig(confidence_threshold=0.6),
        )
        results = pipeline.run([])
        assert len(results) == 1


class TestPipelineAvailability:
    def test_unavailable_detector_skipped(self):
        available = FakeDetector([_detection(text="found@example.com")])
        unavailable = FakeDetector([_detection(text="hidden@example.com")], available=False)

        pipeline = DetectionPipeline(
            [available, unavailable],
            AppConfig(confidence_threshold=0.0),
        )
        results = pipeline.run([])

        assert len(results) == 1
        assert results[0].text == "found@example.com"

    def test_no_detectors_returns_empty(self):
        pipeline = DetectionPipeline([], AppConfig(confidence_threshold=0.0))
        results = pipeline.run([])
        assert results == []
