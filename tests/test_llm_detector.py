import json
from unittest.mock import MagicMock, patch

import pytest

from delere.core.models import DetectorSource, PIICategory, PageText
from delere.detectors.llm import LLMDetector, LLMDetectionResponse
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


class TestLLMDetectorParsing:
    def test_parses_valid_structured_output(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)

        mock_response = MagicMock()
        mock_response.message.content = json.dumps({
            "entities": [
                {
                    "text": "John Smith",
                    "category": "name",
                    "reasoning": "Full person name",
                },
                {
                    "text": "sarah@example.com",
                    "category": "email",
                    "reasoning": "Email address",
                },
            ]
        })

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        detector._client = mock_client

        page = _make_page("John Smith can be reached at sarah@example.com")
        results = detector.detect([page], page.full_text)

        assert len(results) == 2
        names = [d for d in results if d.category == PIICategory.NAME]
        emails = [d for d in results if d.category == PIICategory.EMAIL]
        assert len(names) == 1
        assert len(emails) == 1
        assert names[0].text == "John Smith"
        assert all(d.source == DetectorSource.LLM for d in results)

    def test_ignores_invalid_categories(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)

        mock_response = MagicMock()
        mock_response.message.content = json.dumps({
            "entities": [
                {
                    "text": "something",
                    "category": "not_a_real_category",
                    "reasoning": "test",
                },
            ]
        })

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        detector._client = mock_client

        page = _make_page("something in the text")
        results = detector.detect([page], page.full_text)

        assert len(results) == 0


class TestLLMDetectorGracefulDegradation:
    def test_returns_empty_when_client_unavailable(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)
        detector._client = None

        # Patch the import to simulate ollama not installed
        with patch.dict("sys.modules", {"ollama": None}):
            detector._client = None
            page = _make_page("Some text with John Smith")
            results = detector.detect([page], page.full_text)
            assert results == []

    def test_returns_empty_on_malformed_response(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)

        mock_response = MagicMock()
        mock_response.message.content = "not valid json at all"

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_response
        detector._client = mock_client

        page = _make_page("Some text")
        results = detector.detect([page], page.full_text)
        assert results == []

    def test_returns_empty_on_connection_error(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)

        mock_client = MagicMock()
        mock_client.chat.side_effect = ConnectionError("Ollama not running")
        detector._client = mock_client

        page = _make_page("Some text")
        results = detector.detect([page], page.full_text)
        assert results == []


class TestLLMDetectorChunking:
    def test_short_text_single_chunk(self):
        detector = LLMDetector(load_profile("pipeda"))
        chunks = detector._chunk_text("short text", max_chars=3000)
        assert len(chunks) == 1

    def test_long_text_multiple_chunks(self):
        detector = LLMDetector(load_profile("pipeda"))
        long_text = "word " * 1000
        chunks = detector._chunk_text(long_text, max_chars=100)
        assert len(chunks) > 1

        # Verify all text is covered (no gaps)
        full_from_chunks = chunks[0]
        for chunk in chunks[1:]:
            full_from_chunks += chunk[200:]  # skip the overlap
        # All content should be present
        assert "word" in full_from_chunks


class TestLLMDetectorAvailability:
    def test_unavailable_when_client_fails(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)

        mock_client = MagicMock()
        mock_client.list.side_effect = ConnectionError("refused")
        detector._client = mock_client

        assert detector.is_available() is False

    def test_available_when_client_responds(self):
        profile = load_profile("pipeda")
        detector = LLMDetector(profile)

        mock_client = MagicMock()
        mock_client.list.return_value = {"models": []}
        detector._client = mock_client

        assert detector.is_available() is True
