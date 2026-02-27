from enum import StrEnum

from pydantic import BaseModel, Field


class PIICategory(StrEnum):
    """Categories of personally identifiable information across all compliance frameworks."""

    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    SIN = "sin"
    ADDRESS = "address"
    DATE_OF_BIRTH = "date_of_birth"
    HEALTH_ID = "health_id"
    FINANCIAL = "financial"
    NATIONAL_ID = "national_id"
    IP_ADDRESS = "ip_address"
    PASSPORT = "passport"
    CREDIT_CARD = "credit_card"
    IBAN = "iban"
    VAT_NUMBER = "vat_number"
    DEVICE_ID = "device_id"
    VIN = "vin"
    URL = "url"
    MEDICAL_RECORD_NUMBER = "medical_record_number"
    BIOMETRIC = "biometric"
    PHOTO = "photo"
    OTHER = "other"


class DetectorSource(StrEnum):
    """Which detection layer identified this entity."""

    REGEX = "regex"
    SPACY = "spacy"
    LLM = "llm"


class BoundingBox(BaseModel):
    """A rectangle on a PDF page in PDF coordinate space.

    Carries its own page_number so detections are fully self-contained
    and the redactor never needs to look up which page a detection came from.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int


class Detection(BaseModel):
    """A single PII detection with location and provenance.

    bounding_boxes is a list because multi-word entities like "John Smith"
    may span multiple word boxes on the page.
    """

    text: str
    category: PIICategory
    source: DetectorSource
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    context: str = ""


class PageText(BaseModel):
    """Extracted text from a single PDF page with word-level positions.

    The words list matches the tuple shape returned by pymupdf's
    page.get_text("words"): (x0, y0, x1, y1, word, block_no, line_no, word_no)
    """

    page_number: int
    full_text: str
    words: list[tuple[float, float, float, float, str, int, int, int]]


class RedactionResult(BaseModel):
    """Summary of a completed redaction operation on a single document."""

    input_path: str
    output_path: str
    total_detections: int
    detections_by_category: dict[str, int] = Field(default_factory=dict)
    detections_by_source: dict[str, int] = Field(default_factory=dict)
    pages_processed: int
    compliance_profiles: list[str]
