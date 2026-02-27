# delere

**Secure, compliance-aware PII redaction for PDF documents.**

*delere*

Delere is a document redaction tool built for regulated industries where data privacy isn't optional. Unlike simple redaction tools that draw black boxes over sensitive text, delere **removes PII directly from the PDF content stream**, strips all document metadata, and rewrites the file from scratch. The original text is not hidden. It is destroyed, with no way to recover it.

> **Disclaimer:** Delere is a general-purpose redaction tool. The built-in compliance profiles (PIPEDA, GDPR, HIPAA) provide broad coverage for common PII patterns, but they are not guaranteed to catch every sensitive identifier in every document type. **This tool is provided as-is and does not constitute legal or compliance advice.** Organizations operating under regulatory obligations should validate redaction outputs against their specific requirements. See the [full disclaimer](#disclaimer) below.

---

## Disclaimer

Delere is a general-purpose redaction tool. The built-in compliance profiles (PIPEDA, GDPR, HIPAA) provide broad coverage for common PII patterns, but they are not guaranteed to catch every sensitive identifier in every document type.

For use in production, enterprise, or regulated environments, the detection pipeline should be calibrated to the specific content types, document formats, and data patterns present in your workflows. Different industries, jurisdictions, and document structures may require custom regex patterns, adjusted confidence thresholds, additional detection layers, or domain-specific compliance profiles.

**This tool is provided as-is and does not constitute legal or compliance advice.** Organizations operating under regulatory obligations should validate redaction outputs against their specific requirements and conduct testing with representative document samples before deploying to production.

For questions about enterprise calibration, custom compliance profiles, or consulting engagements, please reach out via [GitHub Issues](https://github.com/r-oc/delere/issues).

---

## Why Delere

Most PDF redaction tools work by placing a visual overlay on top of text. A black rectangle is drawn over the sensitive content, but the underlying data stays in the file. Anyone with a basic PDF reader or text extraction library can pull it right back out. That's not redaction. It's cosmetic.

Delere works differently.

- **Content stream removal.** Detected PII is removed from the PDF's internal content stream using PyMuPDF's `apply_redactions()` with `TEXT_REMOVE`, `IMAGE_REMOVE`, and `LINE_ART_REMOVE` flags. The text is deleted from the file, not covered up.
- **Full file rewrite.** PDFs are never saved incrementally, which is a method that appends changes while leaving the original data intact. Delere rewrites the entire file with `garbage=4` collection, so no residual bytes from the original content remain.
- **Metadata destruction.** The document info dictionary, XMP metadata, annotations, and form fields are all stripped. Nothing that could identify the document's origin, author, or editing history survives the process.
- **Image and graphics cleanup.** Images that overlap with redacted regions are completely removed. Vector graphics touching redacted areas are eliminated. Visual recovery is not possible.

The output is a PDF that contains no trace of the redacted information. Not in the text layer, not in the metadata, and not in leftover file bytes.

---

## Built for Regulated Industries

Delere is designed for environments where document handling is governed by privacy law, including healthcare, finance, legal, government, and any organization that processes personal data under regulatory frameworks.

### Compliance Profiles

Delere ships with built-in profiles for major privacy regulations:

| Profile | Regulation | Coverage |
|---------|-----------|----------|
| `pipeda` | Canadian Personal Information Protection and Electronic Documents Act | SIN, health card numbers (OHIP, RAMQ), Canadian postal codes, phone numbers, names, addresses, dates of birth |
| `gdpr` | EU General Data Protection Regulation | National IDs (French INSEE, Spanish DNI/NIE, Italian Codice Fiscale, German Steuer-ID, Dutch BSN, Swedish Personnummer, Irish PPS), IBAN, VAT numbers, EU phone formats, UK postcodes |
| `hipaa` | US Health Insurance Portability and Accountability Act | SSN, Medicare MBI, DEA numbers, NPI, medical record numbers, VINs, device identifiers, all 18 HIPAA identifier categories |

Profiles are composable. You can apply multiple simultaneously for cross-jurisdictional compliance:

```bash
delere redact document.pdf --compliance pipeda,gdpr
```

Profiles are defined in YAML and fully extensible, so you can add your own organization-specific patterns, categories, and detection rules.

### Audit Trail

Every redaction produces a companion audit manifest (`_audit.json`) that includes:

- SHA-256 hashes of both the input and output files
- Cryptographic hashes of each detected PII string (the actual text is **never** logged)
- Detection source, confidence score, and category for every finding
- Timestamp, tool version, compliance profiles used, and configuration parameters

Auditors can verify that a specific string was redacted by computing its hash against the manifest, without ever needing to see the sensitive data itself.

---

## How It Works

Delere uses a multi-layer detection pipeline. Each layer operates independently, and results are merged, deduplicated, and filtered by confidence threshold before any redaction takes place.

### Detection Layers

**Regex Detection.** Always active. Pre-compiled patterns from compliance profiles run with keyword proximity filtering to reduce false positives. Short numeric patterns (like SIN numbers) only trigger when contextual keywords such as "Social Insurance Number" appear nearby in the text.

**SpaCy NER.** Enabled by default. Named Entity Recognition identifies PII contextually, catching names, locations, organizations, and dates even when no regex pattern matches. Entities are mapped to PII categories through profile-defined rules.

**LLM Detection.** Optional. Uses a locally-hosted Ollama model for deeper contextual analysis. This layer catches indirect identifiers that rules-based systems miss, such as "the patient in room 4" where "room 4" becomes PII in a medical context. All processing stays local. No data leaves your machine.

### Pipeline

```
PDF → Text Extraction (native or OCR) → [Regex + SpaCy + LLM] → Deduplicate → Filter → Review → Redact → Audit
```

When multiple detectors flag the same text on the same page, the highest-confidence detection wins. The configurable confidence threshold (default 0.6) filters out low-certainty matches.

---

## Installation

```bash
pip install delere
```

With optional LLM support:

```bash
pip install delere[llm]
```

SpaCy requires a language model:

```bash
python -m spacy download en_core_web_sm
```

For OCR support (scanned/image-only PDFs), install Tesseract:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt install tesseract-ocr

# Windows
# Download from https://github.com/tesseract-ocr/tesseract
```

Requires Python 3.12+.

---

## Usage

### Redact a PDF

```bash
# Redact under PIPEDA compliance
delere redact document.pdf --compliance pipeda

# Apply multiple compliance profiles
delere redact document.pdf --compliance pipeda,gdpr,hipaa

# Specify output location
delere redact document.pdf --compliance pipeda --output ./redacted/
```

### Review Before Redacting

Review mode displays a table of all detections, including masked text, category, page number, confidence, and detection source. It prompts for confirmation before making any changes.

```bash
delere redact document.pdf --compliance pipeda --review-mode
```

### Batch Processing

Point delere at a directory to process all PDFs with a progress bar:

```bash
delere redact ./documents/ --compliance pipeda --output ./redacted/
```

### Redact Scanned/Image-Only PDFs

Delere can process scanned documents and image-only PDFs using OCR (Optical Character Recognition). When `--ocr` is enabled, pages that contain images but no embedded text are automatically detected and processed with Tesseract OCR. Pages with existing text layers use native extraction for speed and accuracy.

```bash
# Enable OCR for scanned documents
delere redact scanned_document.pdf --compliance pipeda --ocr

# Specify OCR language (defaults to English)
delere redact document_fr.pdf --compliance pipeda --ocr --ocr-language fra
```

For scanned pages, delere paints over PII regions within the image rather than removing the entire page image. The redacted areas are baked into the final PDF and cannot be recovered. The audit manifest records which pages were processed via OCR.

### Tune Detection

```bash
# Raise confidence threshold to reduce false positives
delere redact document.pdf --compliance pipeda --confidence-threshold 0.8

# Enable LLM detection for deeper contextual analysis
delere redact document.pdf --compliance pipeda --ai

# Use a specific Ollama model
delere redact document.pdf --compliance pipeda --ai --model mistral
```

### Explore Profiles

```bash
# List available compliance profiles
delere profiles list

# View profile details (patterns, categories, mappings)
delere profiles show pipeda
```

---

## AI in Regulated Industries

Delere's optional LLM layer is built around a core constraint: **no data leaves your infrastructure**.

The LLM detector runs against [Ollama](https://ollama.com), a local model runtime. Documents are chunked and analyzed entirely on your machine, with nothing sent to external APIs. This makes LLM-powered detection viable in environments where cloud-based AI services are prohibited by policy or regulation.

The value of this layer is in what rules alone can't catch. Regex patterns match known formats. NER models match known entity types. But contextual PII, meaning identifiers that are only sensitive in a given context, requires language understanding. The LLM layer provides that capability without compromising data sovereignty.

For organizations that cannot use AI at all, the LLM layer is off by default. Regex and SpaCy detection provide strong baseline coverage on their own.

---

## Security Model

| Threat | Mitigation |
|--------|------------|
| Text recovery from redacted PDF | Content stream removal: text is deleted, not overlaid |
| Incremental save data recovery | Full file rewrite with `garbage=4` collection |
| Metadata leakage | Info dictionary, XMP, annotations, and form fields stripped |
| Image-based text recovery | Images overlapping redacted regions completely removed (native pages) or painted over (scanned pages) |
| Vector graphics recovery | Line art touching redacted areas removed |
| Audit log PII exposure | Only SHA-256 hashes of detected text stored, never plaintext |
| Data exfiltration via LLM | All LLM processing is local via Ollama, no external API calls |

---

## Configuration

Delere is configurable through CLI flags:

| Option | Default | Description |
|--------|---------|-------------|
| `--compliance` | `pipeda` | Comma-separated compliance profiles |
| `--confidence-threshold` | `0.6` | Minimum detection confidence (0.0–1.0) |
| `--review-mode` | off | Interactive review before redacting |
| `--ai` | off | Enable LLM detection layer |
| `--model` | `llama3.2` | Ollama model for LLM detection |
| `--output` | alongside input | Output file or directory |
| `--ocr` | off | Enable OCR for scanned/image-only pages |
| `--ocr-language` | `eng` | Tesseract language code (e.g., `eng`, `fra`, `deu`) |

Redaction appearance and behavior (fill color, metadata stripping, annotation removal, flattening) are configurable programmatically when using delere as a library.

---

## License

GPL v3
