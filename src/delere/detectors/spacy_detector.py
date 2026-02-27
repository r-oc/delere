from __future__ import annotations

import logging

from delere.core.models import Detection, DetectorSource, PIICategory, PageText
from delere.detectors.base import BaseDetector, find_bounding_boxes
from delere.profiles.loader import ComplianceProfile, SpaCyMapping

logger = logging.getLogger(__name__)


class SpaCyDetector(BaseDetector):
    """PII detection using spaCy named entity recognition.

    Loads the spaCy model lazily on first detect() call to avoid paying
    the startup cost when the detector might not be needed. Only returns
    entities that have a mapping in the compliance profile.
    """

    def __init__(self, profile: ComplianceProfile, model_name: str = "en_core_web_sm") -> None:
        self._model_name = model_name
        self._nlp = None
        self._mappings: dict[str, SpaCyMapping] = {
            m.spacy_label: m for m in profile.spacy_mappings
        }

    def _load_model(self) -> None:
        if self._nlp is not None:
            return
        import spacy

        self._nlp = spacy.load(self._model_name)

    # spaCy tags lots of short text fragments as entities (single numbers,
    # abbreviations, etc). Most of these are not real PII. Requiring at
    # least 3 characters filters out noise like "4" from "Bankruptcies: 4".
    MIN_ENTITY_LENGTH = 3

    # spaCy entity labels that are too noisy to use without additional
    # context. CARDINAL ("4"), ORDINAL ("first"), QUANTITY ("3 kg"),
    # MONEY ("$50"), and PERCENT ("10%") are almost never PII on their own.
    NOISY_LABELS = {"CARDINAL", "ORDINAL", "QUANTITY", "MONEY", "PERCENT"}

    def detect(self, page_texts: list[PageText], full_text: str) -> list[Detection]:
        self._load_model()
        assert self._nlp is not None

        doc = self._nlp(full_text)
        detections: list[Detection] = []

        for ent in doc.ents:
            if ent.label_ in self.NOISY_LABELS:
                continue

            mapping = self._mappings.get(ent.label_)
            if mapping is None:
                continue

            text = ent.text.strip()
            if len(text) < self.MIN_ENTITY_LENGTH:
                continue

            # Pure numeric strings from spaCy are almost always false positives.
            # Dates like "2015" or counts like "4" are not identifiers.
            if text.isdigit():
                continue

            context_start = max(0, ent.start_char - 40)
            context_end = min(len(full_text), ent.end_char + 40)

            detections.append(Detection(
                text=text,
                category=PIICategory(mapping.category),
                source=DetectorSource.SPACY,
                confidence=mapping.confidence,
                bounding_boxes=find_bounding_boxes(text, page_texts),
                context=full_text[context_start:context_end],
            ))

        return detections

    def is_available(self) -> bool:
        try:
            import spacy

            spacy.load(self._model_name)
            return True
        except (OSError, ImportError):
            logger.warning(
                "spaCy model '%s' not available. Install with: "
                "python -m spacy download %s",
                self._model_name,
                self._model_name,
            )
            return False
