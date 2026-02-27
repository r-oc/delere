import pytest

from delere.core.models import DetectorSource, PIICategory, PageText
from delere.detectors.spacy_detector import SpaCyDetector
from delere.profiles.loader import load_profile


def _make_page(text: str, page_number: int = 0) -> PageText:
    words = []
    x = 72.0
    for block_no, line in enumerate(text.split("\n")):
        for word_no, word in enumerate(line.split()):
            width = len(word) * 7.0
            words.append((x, 100.0, x + width, 112.0, word, block_no, 0, word_no))
            x += width + 7.0
        x = 72.0
    return PageText(page_number=page_number, full_text=text, words=words)


@pytest.fixture
def pipeda_spacy():
    detector = SpaCyDetector(load_profile("pipeda"))
    if not detector.is_available():
        pytest.skip("spaCy model en_core_web_sm not installed")
    return detector


class TestSpaCyDetection:
    def test_detects_person_name(self, pipeda_spacy: SpaCyDetector):
        page = _make_page("Dr. Sarah Thompson submitted the application on Monday.")
        results = pipeda_spacy.detect([page], page.full_text)

        names = [d for d in results if d.category == PIICategory.NAME]
        assert len(names) >= 1
        assert any("Sarah Thompson" in d.text for d in names)

    def test_detection_source_is_spacy(self, pipeda_spacy: SpaCyDetector):
        page = _make_page("Contact John Smith at the Toronto office.")
        results = pipeda_spacy.detect([page], page.full_text)

        for det in results:
            assert det.source == DetectorSource.SPACY

    def test_unmapped_entities_ignored(self, pipeda_spacy: SpaCyDetector):
        """ORG is not mapped in PIPEDA profile, so organization names should not appear."""
        page = _make_page("Microsoft and Google announced a partnership.")
        results = pipeda_spacy.detect([page], page.full_text)

        # PIPEDA profile does not map ORG to any category
        # All results should be from mapped labels only
        mapped_categories = {PIICategory.NAME, PIICategory.ADDRESS, PIICategory.DATE_OF_BIRTH}
        for det in results:
            assert det.category in mapped_categories

    def test_empty_text(self, pipeda_spacy: SpaCyDetector):
        page = _make_page("")
        results = pipeda_spacy.detect([page], page.full_text)
        assert results == []

    def test_gpe_mapped_to_address(self, pipeda_spacy: SpaCyDetector):
        page = _make_page("She traveled from Ottawa to Vancouver last week.")
        results = pipeda_spacy.detect([page], page.full_text)

        addresses = [d for d in results if d.category == PIICategory.ADDRESS]
        # spaCy should recognize Ottawa and Vancouver as GPE
        gpe_texts = [d.text for d in addresses]
        assert any("Ottawa" in t or "Vancouver" in t for t in gpe_texts)
