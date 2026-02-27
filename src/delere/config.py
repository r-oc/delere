from pathlib import Path

from pydantic import BaseModel, Field


class OcrConfig(BaseModel):
    """Controls OCR behavior for scanned/image-only pages."""

    enabled: bool = False
    language: str = "eng"
    min_text_threshold: int = 10
    dpi: int = 300


class DetectorConfig(BaseModel):
    """Controls which detection layers are active and their settings."""

    regex_enabled: bool = True
    spacy_enabled: bool = True
    spacy_model: str = "en_core_web_sm"
    llm_enabled: bool = False
    llm_model: str = "llama3.2"
    llm_base_url: str = "http://localhost:11434"


class RedactionConfig(BaseModel):
    """Controls redaction appearance and security settings."""

    fill_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    strip_metadata: bool = True
    remove_annotations: bool = True
    flatten_after_redaction: bool = True


class AppConfig(BaseModel):
    """Top-level application configuration.

    Constructed in the CLI layer and passed down to all components.
    Not a singleton; this keeps every component independently testable.
    """

    compliance_profiles: list[str] = Field(default_factory=lambda: ["pipeda"])
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    output_dir: Path | None = None
    output_suffix: str = "_redacted"
    review_mode: bool = False
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
