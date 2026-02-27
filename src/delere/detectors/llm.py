from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from delere.core.models import Detection, DetectorSource, PIICategory, PageText
from delere.detectors.base import BaseDetector, find_bounding_boxes
from delere.profiles.loader import ComplianceProfile

logger = logging.getLogger(__name__)


class LLMEntity(BaseModel):
    """A single PII entity identified by the LLM."""

    text: str
    category: str
    reasoning: str = ""


class LLMDetectionResponse(BaseModel):
    """Structured response from the LLM for PII detection."""

    entities: list[LLMEntity]


class LLMDetector(BaseDetector):
    """Contextual PII detection using a local Ollama LLM.

    Sends document text to a locally-running Ollama model with a structured
    prompt asking it to identify PII entities. The model returns structured
    JSON which is validated with Pydantic.

    This detector is optional and off by default. It catches context-dependent
    PII that regex and NER miss, like "the patient on bed 3" where "bed 3"
    is an indirect identifier.
    """

    def __init__(
        self,
        profile: ComplianceProfile,
        model_name: str = "llama3.2",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._profile = profile
        self._model_name = model_name
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-load the Ollama client. Only imports ollama when needed."""
        if self._client is None:
            try:
                from ollama import Client

                self._client = Client(host=self._base_url)
            except ImportError:
                logger.warning("ollama package not installed")
                return None
        return self._client

    def detect(self, page_texts: list[PageText], full_text: str) -> list[Detection]:
        client = self._get_client()
        if client is None:
            return []

        chunks = self._chunk_text(full_text, max_chars=3000)
        all_detections: list[Detection] = []

        for chunk in chunks:
            prompt = self._build_prompt(chunk)
            try:
                response = client.chat(
                    model=self._model_name,
                    messages=[{"role": "user", "content": prompt}],
                    format=LLMDetectionResponse.model_json_schema(),
                    options={"temperature": 0},
                )
                parsed = LLMDetectionResponse.model_validate_json(
                    response.message.content
                )
                detections = self._convert_to_detections(parsed, page_texts)
                all_detections.extend(detections)
            except Exception as e:
                logger.warning("LLM detection failed for chunk: %s", e)
                continue

        return all_detections

    def _build_prompt(self, text_chunk: str) -> str:
        categories = ", ".join(self._profile.categories)
        context = self._profile.llm_prompt_context or ""

        return (
            "You are a PII detection system. Analyze the following text and identify "
            "all personally identifiable information.\n\n"
            f"Compliance context: {context}\n\n"
            f"Categories to detect: {categories}\n\n"
            f"Text to analyze:\n{text_chunk}\n\n"
            "Return a JSON object with an 'entities' array. Each entity must have "
            f"'text' (the exact PII string found), 'category' (one of: {categories}), "
            "and 'reasoning' (brief explanation of why this is PII)."
        )

    def _chunk_text(self, text: str, max_chars: int = 3000) -> list[str]:
        """Split text into overlapping chunks to stay within context limits.

        Uses a 200-character overlap so entities at chunk boundaries
        are not missed. The pipeline's deduplication handles any
        duplicate detections from the overlapping regions.
        """
        if len(text) <= max_chars:
            return [text]

        overlap = min(200, max_chars // 2)
        step = max_chars - overlap
        chunks: list[str] = []

        for start in range(0, len(text), step):
            chunks.append(text[start : start + max_chars])
            if start + max_chars >= len(text):
                break

        return chunks

    def _convert_to_detections(
        self, response: LLMDetectionResponse, page_texts: list[PageText]
    ) -> list[Detection]:
        valid_categories = {c.value for c in PIICategory}
        detections: list[Detection] = []

        for entity in response.entities:
            category_str = entity.category.lower().strip()
            if category_str not in valid_categories:
                continue

            detections.append(Detection(
                text=entity.text,
                category=PIICategory(category_str),
                source=DetectorSource.LLM,
                confidence=0.7,
                bounding_boxes=find_bounding_boxes(entity.text, page_texts),
                context=entity.reasoning,
            ))

        return detections

    def is_available(self) -> bool:
        """Check if Ollama is running and reachable."""
        try:
            client = self._get_client()
            if client is None:
                return False
            client.list()
            return True
        except Exception:
            return False
