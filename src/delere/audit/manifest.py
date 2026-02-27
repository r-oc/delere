import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from delere import __version__
from delere.core.models import Detection, RedactionResult


class AuditEntry(BaseModel):
    """A single detection in the audit log.

    Stores a SHA-256 hash of the detected text rather than the text itself,
    so the audit log does not become a PII liability. An auditor can verify
    a specific string was redacted by hashing it and checking the manifest.
    """

    category: str
    source: str
    confidence: float
    text_hash: str
    page_numbers: list[int]


class AuditManifest(BaseModel):
    """Complete audit record for a redaction operation."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tool_version: str = __version__
    input_file: str
    input_file_hash: str
    output_file: str
    output_file_hash: str
    compliance_profiles: list[str]
    confidence_threshold: float
    detection_layers: list[str]
    total_detections: int
    entries: list[AuditEntry]
    metadata_stripped: bool
    secure_redaction: bool
    ocr_pages: list[int] = Field(default_factory=list)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def create_manifest(
    result: RedactionResult,
    detections: list[Detection],
    input_path: Path,
    output_path: Path,
    confidence_threshold: float,
    review_mode: bool = False,
    ocr_pages: list[int] | None = None,
) -> AuditManifest:
    """Build an audit manifest from redaction results."""
    entries = []
    for det in detections:
        pages = sorted({bb.page_number for bb in det.bounding_boxes})
        entries.append(AuditEntry(
            category=det.category.value,
            source=det.source.value,
            confidence=det.confidence,
            text_hash=_sha256_text(det.text),
            page_numbers=pages,
        ))

    layers = sorted(result.detections_by_source.keys())

    return AuditManifest(
        input_file=str(input_path),
        input_file_hash=_sha256_file(input_path),
        output_file=str(output_path),
        output_file_hash=_sha256_file(output_path),
        compliance_profiles=result.compliance_profiles,
        confidence_threshold=confidence_threshold,
        detection_layers=layers,
        total_detections=result.total_detections,
        entries=entries,
        metadata_stripped=not review_mode,
        secure_redaction=not review_mode,
        ocr_pages=sorted(ocr_pages) if ocr_pages else [],
    )


def save_manifest(manifest: AuditManifest, output_path: Path) -> Path:
    """Write the manifest as JSON alongside the redacted PDF.

    The manifest file is named after the output PDF with _audit.json suffix.
    """
    manifest_path = output_path.with_name(
        output_path.stem + "_audit.json"
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False)
    )
    return manifest_path
