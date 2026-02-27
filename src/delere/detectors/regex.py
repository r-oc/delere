import regex

from delere.core.models import Detection, DetectorSource, PIICategory, PageText
from delere.detectors.base import BaseDetector, find_bounding_boxes
from delere.profiles.loader import ComplianceProfile, PatternDef


class RegexDetector(BaseDetector):
    """Deterministic PII detection using compiled regular expressions.

    Pre-compiles all patterns from the compliance profile at init time
    for fast iteration during detection. Supports keyword proximity
    filtering to reduce false positives on short numeric patterns.
    """

    def __init__(self, profile: ComplianceProfile) -> None:
        self._compiled = self._compile_patterns(profile.patterns)

    def _compile_patterns(
        self, pattern_defs: list[PatternDef]
    ) -> list[tuple[PatternDef, regex.Pattern[str]]]:
        compiled = []
        for pdef in pattern_defs:
            try:
                compiled.append((pdef, regex.compile(pdef.pattern, regex.IGNORECASE)))
            except regex.error:
                # Skip malformed patterns rather than crashing the whole detector
                continue
        return compiled

    def detect(self, page_texts: list[PageText], full_text: str) -> list[Detection]:
        detections: list[Detection] = []

        for pdef, compiled in self._compiled:
            for match in compiled.finditer(full_text):
                # If the pattern has a capturing group, use it as the PII value.
                # This lets patterns like "Surname\s*(PATEL)" redact "PATEL"
                # instead of "Surname PATEL".
                if match.lastindex and match.lastindex >= 1:
                    matched_text = match.group(1)
                else:
                    matched_text = match.group()

                start, end = match.span()

                if not self._passes_keyword_check(pdef, full_text, start, end):
                    continue

                context_start = max(0, start - 40)
                context_end = min(len(full_text), end + 40)

                detections.append(Detection(
                    text=matched_text,
                    category=PIICategory(pdef.category),
                    source=DetectorSource.REGEX,
                    confidence=pdef.confidence,
                    bounding_boxes=find_bounding_boxes(matched_text, page_texts),
                    context=full_text[context_start:context_end],
                ))

        return detections

    def _passes_keyword_check(
        self, pdef: PatternDef, full_text: str, start: int, end: int
    ) -> bool:
        """For patterns requiring keyword proximity, check that at least one
        keyword appears within the configured window around the match.
        """
        if not pdef.requires_keyword_proximity:
            return True

        window_start = max(0, start - pdef.keyword_window)
        window_end = min(len(full_text), end + pdef.keyword_window)
        context = full_text[window_start:window_end].lower()

        return any(kw.lower() in context for kw in pdef.keywords)

    def is_available(self) -> bool:
        return True
