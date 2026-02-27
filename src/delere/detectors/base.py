from abc import ABC, abstractmethod

from delere.core.models import BoundingBox, Detection, PageText


class BaseDetector(ABC):
    """Contract that every detection layer must satisfy."""

    @abstractmethod
    def detect(self, page_texts: list[PageText], full_text: str) -> list[Detection]:
        """Scan extracted text and return PII detections.

        Args:
            page_texts: Per-page extracted text with word-level bounding boxes.
            full_text: The complete document text concatenated across all pages.

        Returns:
            List of Detection objects with bounding boxes populated.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether this detector can run (dependencies present, etc.)."""
        ...


def _strip_punctuation(text: str) -> str:
    """Remove leading/trailing punctuation for fuzzy word comparison."""
    return text.strip("()[]{}.,;:!?\"'")


def find_bounding_boxes(text: str, page_texts: list[PageText]) -> list[BoundingBox]:
    """Map a matched text string back to word-level bounding boxes on PDF pages.

    Uses two strategies:
    1. Exact word sequence matching (handles clean multi-word entities)
    2. Substring containment matching (handles cases where regex captures
       partial words or punctuation differs between match and PDF words)

    Returns a BoundingBox for each matched word found on the page.
    """
    target_words = text.split()
    if not target_words:
        return []

    bboxes: list[BoundingBox] = []

    for page in page_texts:
        page_word_texts = [w[4] for w in page.words]

        # Strategy 1: exact word sequence match (with punctuation stripping)
        found = _match_word_sequence(target_words, page_word_texts, page)
        if found:
            bboxes.extend(found)
            continue

        # Strategy 2: find words that contain parts of the target text
        found = _match_by_containment(text, page_word_texts, page)
        if found:
            bboxes.extend(found)

    return bboxes


def _match_word_sequence(
    target_words: list[str], page_word_texts: list[str], page: PageText
) -> list[BoundingBox]:
    """Try to find the target words as a consecutive sequence in the page words.

    Compares with punctuation stripped so that "(416)" matches "416)".
    """
    target_len = len(target_words)
    stripped_targets = [_strip_punctuation(w).lower() for w in target_words]

    for i in range(len(page_word_texts) - target_len + 1):
        match = all(
            _strip_punctuation(page_word_texts[i + j]).lower() == stripped_targets[j]
            for j in range(target_len)
        )
        if match:
            return [
                BoundingBox(
                    x0=page.words[i + j][0],
                    y0=page.words[i + j][1],
                    x1=page.words[i + j][2],
                    y1=page.words[i + j][3],
                    page_number=page.page_number,
                )
                for j in range(target_len)
            ]
    return []


def _match_by_containment(
    text: str, page_word_texts: list[str], page: PageText
) -> list[BoundingBox]:
    """Find page words whose text appears within the target string.

    Handles cases where the regex match spans parts of PDF words differently
    than expected. Collects all words that contribute to the matched text.
    """
    text_lower = text.lower()
    bboxes: list[BoundingBox] = []

    for i, page_word in enumerate(page_word_texts):
        stripped = _strip_punctuation(page_word).lower()
        if not stripped:
            continue
        # Check if this word's content is part of the matched text
        if stripped in text_lower:
            bboxes.append(BoundingBox(
                x0=page.words[i][0],
                y0=page.words[i][1],
                x1=page.words[i][2],
                y1=page.words[i][3],
                page_number=page.page_number,
            ))

    return bboxes
