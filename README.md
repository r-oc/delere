# delere

**Secure, compliance-aware PII redaction for PDF documents.**

*delere*

Delere is a document redaction tool built for regulated industries where data privacy isn't optional. Unlike simple redaction tools that draw black boxes over sensitive text, delere **removes PII directly from the PDF content stream**, strips all document metadata, and rewrites the file from scratch. The original text is not hidden — it is destroyed. There is no way to recover it.

---

## Why Delere

Most PDF redaction tools apply a visual overlay — a black rectangle drawn on top of text. The underlying data remains in the file and can be trivially extracted with any PDF reader or text extraction library. This is not redaction. It is decoration.

Delere takes a fundamentally different approach:

- **Content stream removal** — Detected PII is removed from the PDF's internal content stream using PyMuPDF's `apply_redactions()` with `TEXT_REMOVE`, `IMAGE_REMOVE`, and `LINE_ART_REMOVE` flags. The text is deleted from the file, not covered up.
- **Full file rewrite** — PDFs are never saved incrementally (which appends new data while leaving the original intact). Delere rewrites the entire file with `garbage=4` collection, ensuring no residual bytes from the original content remain.
- **Metadata destruction** — The document info dictionary, XMP metadata, annotations, and form fields are all stripped. Nothing that could identify the document's origin, author, or editing history survives.
- **Image and graphics cleanup** — Images overlapping redacted regions are completely removed. Vector graphics touching redacted areas are eliminated. Visual recovery is not possible.

The result is a PDF that contains no trace of the redacted information — not in the text layer, not in the metadata, not in residual file bytes.

---

## Built for Regulated Industries

Delere is designed for environments where document handling is governed by privacy law: healthcare, finance, legal, government, and any organization processing personal data under regulatory frameworks.

### Compliance Profiles

Delere ships with built-in profiles for major privacy regulations:

| Profile | Regulation | Coverage |
|---------|-----------|----------|
| `pipeda` | Canadian Personal Information Protection and Electronic Documents Act | SIN, health card numbers (OHIP, RAMQ), Canadian postal codes, phone numbers, names, addresses, dates of birth |
| `gdpr` | EU General Data Protection Regulation | National IDs (French INSEE, Spanish DNI/NIE, Italian Codice Fiscale, German Steuer-ID, Dutch BSN, Swedish Personnummer, Irish PPS), IBAN, VAT numbers, EU phone formats, UK postcodes |
| `hipaa` | US Health Insurance Portability and Accountability Act | SSN, Medicare MBI, DEA numbers, NPI, medical record numbers, VINs, device identifiers, all 18 HIPAA identifier categories |

Profiles are composable — apply multiple simultaneously for cross-jurisdictional compliance:

```bash
delere redact document.pdf --compliance pipeda,gdpr
```

Profiles are defined in YAML and fully extensible. Add your own organization-specific patterns, categories, and detection rules.

### Audit Trail

Every redaction produces a companion audit manifest (`_audit.json`) containing:

- SHA-256 hashes of both the input and output files
- Cryptographic hashes of each detected PII string (the actual text is **never** logged)
- Detection source, confidence score, and category for every finding
- Timestamp, tool version, compliance profiles used, and configuration parameters

Auditors can verify that a specific string was redacted by computing its hash against the manifest — without ever seeing the sensitive data.

---

## How It Works

Delere uses a multi-layer detection pipeline. Each layer operates independently, and results are merged, deduplicated, and filtered by confidence threshold before redaction.

### Detection Layers

**Regex Detection** — Always active. Pre-compiled patterns from compliance profiles with keyword proximity filtering to reduce false positives. Short numeric patterns (e.g., SIN numbers) only trigger when contextual keywords like "Social Insurance Number" appear nearby.

**SpaCy NER** — Enabled by default. Named Entity Recognition identifies PII contextually — names, locations, organizations, dates — even when no regex pattern matches. Entities are mapped to PII categories through profile-defined rules.

**LLM Detection** — Optional. Uses a locally-hosted Ollama model for deep contextual analysis. Catches indirect identifiers that rules-based systems miss — things like "the patient in room 4" where "room 4" becomes PII in a medical context. All processing stays local. No data leaves your machine.

### Pipeline

```
PDF → Text Extraction → [Regex + SpaCy + LLM] → Deduplicate → Filter → Review → Redact → Audit
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

Review mode displays a table of all detections — masked text, category, page number, confidence, and detection source — and prompts for confirmation before making any changes.

```bash
delere redact document.pdf --compliance pipeda --review-mode
```

### Batch Processing

Point delere at a directory to process all PDFs with a progress bar:

```bash
delere redact ./documents/ --compliance pipeda --output ./redacted/
```

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

Delere's optional LLM layer is designed with a core constraint: **no data leaves your infrastructure**.

The LLM detector runs against [Ollama](https://ollama.com), a local model runtime. Documents are chunked and analyzed on your machine — nothing is sent to external APIs. This makes LLM-powered detection viable in environments where cloud-based AI services are prohibited by policy or regulation.

The LLM layer catches what rules can't. Regex patterns match known formats. NER models match known entity types. But contextual PII — identifiers that are only sensitive in context — requires language understanding. The LLM layer provides this without compromising data sovereignty.

For organizations that cannot use AI at all, the LLM layer is off by default. Regex and SpaCy detection provide strong coverage without it.

---

## Security Model

| Threat | Mitigation |
|--------|------------|
| Text recovery from redacted PDF | Content stream removal — text deleted, not overlaid |
| Incremental save data recovery | Full file rewrite with `garbage=4` collection |
| Metadata leakage | Info dictionary, XMP, annotations, and form fields stripped |
| Image-based text recovery | Images overlapping redacted regions completely removed |
| Vector graphics recovery | Line art touching redacted areas removed |
| Audit log PII exposure | Only SHA-256 hashes of detected text stored — never plaintext |
| Data exfiltration via LLM | All LLM processing is local via Ollama — no external API calls |

---

## Configuration

Delere is configurable through CLI flags. Key options:

| Option | Default | Description |
|--------|---------|-------------|
| `--compliance` | `pipeda` | Comma-separated compliance profiles |
| `--confidence-threshold` | `0.6` | Minimum detection confidence (0.0–1.0) |
| `--review-mode` | off | Interactive review before redacting |
| `--ai` | off | Enable LLM detection layer |
| `--model` | `llama3.2` | Ollama model for LLM detection |
| `--output` | alongside input | Output file or directory |

Redaction appearance and behavior (fill color, metadata stripping, annotation removal, flattening) are configurable programmatically when using delere as a library.

---

## License

GPL v3
