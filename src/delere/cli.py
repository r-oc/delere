from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from delere.audit.manifest import create_manifest, save_manifest
from delere.config import AppConfig, DetectorConfig, OcrConfig, RedactionConfig
from delere.core.extractor import extract_text
from delere.core.models import Detection, RedactionResult
from delere.core.pipeline import DetectionPipeline
from delere.core.redactor import PDFRedactor
from delere.detectors.base import BaseDetector
from delere.detectors.regex import RegexDetector
from delere.detectors.spacy_detector import SpaCyDetector
from delere.profiles.loader import (
    ComplianceProfile,
    load_profile,
    load_profiles,
    list_profiles,
    merge_profiles,
)

app = typer.Typer(
    name="delere",
    help="Secure, compliance-aware PII redaction for PDF documents.",
    no_args_is_help=True,
)
console = Console()

profiles_app = typer.Typer(help="Manage compliance profiles.")
app.add_typer(profiles_app, name="profiles")

config_app = typer.Typer(help="View and set configuration.")
app.add_typer(config_app, name="config")


def _build_detectors(profile: ComplianceProfile, config: AppConfig) -> list[BaseDetector]:
    """Assemble the detector stack based on config flags."""
    detectors: list[BaseDetector] = []

    if config.detector.regex_enabled:
        detectors.append(RegexDetector(profile))

    if config.detector.spacy_enabled:
        detector = SpaCyDetector(profile, config.detector.spacy_model)
        if detector.is_available():
            detectors.append(detector)
        else:
            console.print(
                "[yellow]spaCy model not available. "
                f"Install with: python -m spacy download {config.detector.spacy_model}[/yellow]"
            )

    if config.detector.llm_enabled:
        try:
            from delere.detectors.llm import LLMDetector

            detector = LLMDetector(
                profile, config.detector.llm_model, config.detector.llm_base_url
            )
            if detector.is_available():
                detectors.append(detector)
            else:
                console.print(
                    "[yellow]Ollama not available. Continuing without LLM detection.[/yellow]"
                )
        except ImportError:
            console.print(
                "[yellow]ollama package not installed. "
                "Install with: pip install delere[llm][/yellow]"
            )

    return detectors


def _resolve_output_path(
    input_path: Path, output: Path | None, suffix: str
) -> Path:
    """Determine the output file path based on user options."""
    if output is not None:
        if output.is_dir() or str(output).endswith("/"):
            output.mkdir(parents=True, exist_ok=True)
            return output / f"{input_path.stem}{suffix}.pdf"
        return output
    return input_path.parent / f"{input_path.stem}{suffix}.pdf"


def _display_detections(detections: list[Detection]) -> None:
    """Show a Rich table of detections for review mode."""
    table = Table(title="Detected PII")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Text (masked)", style="red")
    table.add_column("Page", justify="right")
    table.add_column("Layer", style="green")
    table.add_column("Confidence", justify="right")

    for i, det in enumerate(detections, 1):
        # Mask the middle portion of detected text for review display
        text = det.text
        if len(text) > 4:
            visible = max(2, len(text) // 4)
            masked = text[:visible] + "*" * (len(text) - visible * 2) + text[-visible:]
        else:
            masked = "*" * len(text)

        page = str(det.bounding_boxes[0].page_number + 1) if det.bounding_boxes else "?"

        table.add_row(
            str(i),
            det.category.value,
            masked,
            page,
            det.source.value,
            f"{det.confidence:.0%}",
        )

    console.print(table)


def _display_result(result: RedactionResult) -> None:
    """Print a summary table of the redaction results."""
    table = Table(title="Redaction Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Pages processed", str(result.pages_processed))
    table.add_row("Total detections", str(result.total_detections))

    for cat, count in sorted(result.detections_by_category.items()):
        table.add_row(f"  {cat}", str(count))

    table.add_row("", "")
    for source, count in sorted(result.detections_by_source.items()):
        table.add_row(f"  by {source}", str(count))

    console.print(table)


def _process_single(
    input_path: Path,
    output: Path | None,
    pipeline: DetectionPipeline,
    redactor: PDFRedactor,
    config: AppConfig,
) -> None:
    """Process a single PDF file through the full redaction pipeline."""
    if not input_path.exists():
        console.print(f"[red]File not found: {input_path}[/red]")
        raise typer.Exit(1)

    if not input_path.suffix.lower() == ".pdf":
        console.print(f"[red]Not a PDF file: {input_path}[/red]")
        raise typer.Exit(1)

    console.print(f"Processing [bold]{input_path.name}[/bold]...")

    ocr_cfg = config.ocr if config.ocr.enabled else None
    page_texts = extract_text(input_path, ocr_config=ocr_cfg)

    ocr_pages = frozenset(pt.page_number for pt in page_texts if pt.is_ocr)
    if ocr_pages:
        console.print(
            f"[yellow]OCR applied to {len(ocr_pages)} image-only page(s): "
            f"{sorted(p + 1 for p in ocr_pages)}[/yellow]"
        )

    detections = pipeline.run(page_texts)

    if not detections:
        console.print("[green]No PII detected.[/green]")
        return

    if config.review_mode:
        _display_detections(detections)
        if not typer.confirm("Proceed with redaction?"):
            console.print("Redaction cancelled.")
            return

    output_path = _resolve_output_path(input_path, output, config.output_suffix)

    result = redactor.redact(
        input_path,
        output_path,
        detections,
        config.compliance_profiles,
        review_mode=False,
        ocr_pages=ocr_pages,
    )

    # Generate audit manifest
    manifest = create_manifest(
        result, detections, input_path, output_path, config.confidence_threshold,
        ocr_pages=sorted(ocr_pages),
    )
    manifest_path = save_manifest(manifest, output_path)

    _display_result(result)
    console.print(f"\nOutput: [bold]{output_path}[/bold]")
    console.print(f"Audit:  [bold]{manifest_path}[/bold]")


def _process_directory(
    input_dir: Path,
    output: Path | None,
    pipeline: DetectionPipeline,
    redactor: PDFRedactor,
    config: AppConfig,
) -> None:
    """Process all PDFs in a directory with a progress bar."""
    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        console.print("[yellow]No PDF files found in directory.[/yellow]")
        return

    console.print(f"Found [bold]{len(pdfs)}[/bold] PDF files.\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Redacting PDFs...", total=len(pdfs))
        for pdf_path in pdfs:
            try:
                _process_single(pdf_path, output, pipeline, redactor, config)
            except typer.Exit:
                pass
            progress.advance(task)


@app.command()
def redact(
    path: Path = typer.Argument(..., help="PDF file or directory to redact."),
    compliance: str = typer.Option(
        "pipeda",
        "--compliance",
        "-c",
        help="Comma-separated compliance profiles (e.g., pipeda,gdpr).",
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output path."),
    review_mode: bool = typer.Option(
        False, "--review-mode", help="Show detections and confirm before redacting."
    ),
    confidence_threshold: float = typer.Option(
        0.6, "--confidence-threshold", "-t", help="Minimum confidence score (0.0 to 1.0)."
    ),
    ai: bool = typer.Option(False, "--ai", help="Enable Ollama LLM detector."),
    model: str = typer.Option("llama3.2", "--model", "-m", help="Ollama model name."),
    ocr: bool = typer.Option(False, "--ocr", help="Enable OCR for scanned/image-only pages."),
    ocr_language: str = typer.Option(
        "eng", "--ocr-language", help="Tesseract language code for OCR (e.g., eng, fra, deu)."
    ),
) -> None:
    """Redact PII from a PDF file or directory of PDFs."""
    profile_names = [p.strip() for p in compliance.split(",")]

    config = AppConfig(
        compliance_profiles=profile_names,
        confidence_threshold=confidence_threshold,
        review_mode=review_mode,
        detector=DetectorConfig(llm_enabled=ai, llm_model=model),
        ocr=OcrConfig(enabled=ocr, language=ocr_language),
    )

    if config.ocr.enabled:
        from delere.core.extractor import is_ocr_available

        if not is_ocr_available():
            console.print(
                "[red]OCR requested but Tesseract is not available.[/red]\n"
                "Install Tesseract: https://github.com/tesseract-ocr/tesseract\n"
                "  macOS:   brew install tesseract\n"
                "  Ubuntu:  sudo apt install tesseract-ocr\n"
                "  Windows: download from GitHub releases"
            )
            raise typer.Exit(1)

    try:
        profiles = load_profiles(profile_names)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    merged = merge_profiles(profiles)
    detectors = _build_detectors(merged, config)

    if not detectors:
        console.print("[red]No detection layers available. Cannot proceed.[/red]")
        raise typer.Exit(1)

    pipeline = DetectionPipeline(detectors, config)
    redactor = PDFRedactor(config.redaction)

    if path.is_dir():
        _process_directory(path, output, pipeline, redactor, config)
    else:
        _process_single(path, output, pipeline, redactor, config)


@profiles_app.command("list")
def profiles_list() -> None:
    """List all available compliance profiles."""
    for name in list_profiles():
        console.print(f"  {name}")


@profiles_app.command("show")
def profiles_show(
    name: str = typer.Argument(..., help="Profile name to display."),
) -> None:
    """Show details of a compliance profile."""
    try:
        profile = load_profile(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]{profile.display_name}[/bold]")
    console.print(f"{profile.description}\n")

    table = Table(title="Detection Patterns")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Confidence", justify="right")
    table.add_column("Keyword Required")

    for p in profile.patterns:
        table.add_row(
            p.name,
            p.category,
            f"{p.confidence:.0%}",
            "yes" if p.requires_keyword_proximity else "no",
        )
    console.print(table)

    if profile.spacy_mappings:
        spacy_table = Table(title="spaCy Entity Mappings")
        spacy_table.add_column("spaCy Label", style="cyan")
        spacy_table.add_column("Maps To", style="green")
        spacy_table.add_column("Confidence", justify="right")

        for m in profile.spacy_mappings:
            spacy_table.add_row(m.spacy_label, m.category, f"{m.confidence:.0%}")
        console.print(spacy_table)

    console.print(f"\nCategories: {', '.join(profile.categories)}")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration defaults."""
    config = AppConfig()
    console.print_json(config.model_dump_json(indent=2))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key."),
    value: str = typer.Argument(..., help="Configuration value."),
) -> None:
    """Set a configuration value."""
    console.print("[yellow]Persistent config not yet implemented.[/yellow]")
    console.print(f"Would set [bold]{key}[/bold] = [bold]{value}[/bold]")
