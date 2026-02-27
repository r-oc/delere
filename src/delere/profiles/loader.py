from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_BUILTIN_DIR = Path(__file__).parent


class PatternDef(BaseModel):
    """A regex pattern for detecting a specific PII entity type.

    requires_keyword_proximity controls whether the pattern only fires when
    one of the listed keywords appears within keyword_window characters.
    This is critical for short numeric patterns like SIN or BSN that would
    otherwise produce massive false positives.
    """

    name: str
    pattern: str
    category: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    requires_keyword_proximity: bool = False
    keywords: list[str] = Field(default_factory=list)
    keyword_window: int = 50


class SpaCyMapping(BaseModel):
    """Maps a spaCy NER label to a PII category."""

    spacy_label: str
    category: str
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class ComplianceProfile(BaseModel):
    """A complete compliance profile loaded from YAML.

    Profiles define which PII categories are relevant under a given regulation,
    what regex patterns to use for detection, how spaCy entity labels map to
    PII categories, and additional context for the optional LLM detector.
    """

    name: str
    display_name: str
    description: str
    version: str = "1.0"
    categories: list[str]
    patterns: list[PatternDef] = Field(default_factory=list)
    spacy_mappings: list[SpaCyMapping] = Field(default_factory=list)
    llm_prompt_context: str = ""


def list_profiles(extra_dirs: list[Path] | None = None) -> list[str]:
    """Return names of all available profiles from built-in and extra directories."""
    dirs = [_BUILTIN_DIR]
    if extra_dirs:
        dirs.extend(extra_dirs)

    names: set[str] = set()
    for d in dirs:
        if d.is_dir():
            names.update(p.stem for p in d.glob("*.yaml"))
    return sorted(names)


def load_profile(name: str, extra_dirs: list[Path] | None = None) -> ComplianceProfile:
    """Load a compliance profile by name.

    Searches extra directories first (user overrides), then the built-in directory.
    """
    search_dirs = list(extra_dirs or []) + [_BUILTIN_DIR]

    for d in search_dirs:
        path = d / f"{name}.yaml"
        if path.exists():
            raw = yaml.safe_load(path.read_text())
            return ComplianceProfile(**raw)

    available = list_profiles(extra_dirs)
    raise FileNotFoundError(
        f"No compliance profile named '{name}'. Available: {', '.join(available)}"
    )


def load_profiles(
    names: list[str], extra_dirs: list[Path] | None = None
) -> list[ComplianceProfile]:
    """Load multiple profiles by name."""
    return [load_profile(name, extra_dirs) for name in names]


def merge_profiles(profiles: list[ComplianceProfile]) -> ComplianceProfile:
    """Combine multiple profiles into a single working profile.

    Unions all categories, deduplicates patterns by name (first occurrence wins),
    merges spaCy mappings, and joins LLM prompt context strings.
    """
    if len(profiles) == 1:
        return profiles[0]

    all_categories: list[str] = []
    seen_categories: set[str] = set()

    all_patterns: list[PatternDef] = []
    seen_pattern_names: set[str] = set()

    all_spacy_mappings: list[SpaCyMapping] = []
    seen_spacy_keys: set[str] = set()

    llm_contexts: list[str] = []

    for profile in profiles:
        for cat in profile.categories:
            if cat not in seen_categories:
                all_categories.append(cat)
                seen_categories.add(cat)

        for pattern in profile.patterns:
            if pattern.name not in seen_pattern_names:
                all_patterns.append(pattern)
                seen_pattern_names.add(pattern.name)

        for mapping in profile.spacy_mappings:
            key = f"{mapping.spacy_label}:{mapping.category}"
            if key not in seen_spacy_keys:
                all_spacy_mappings.append(mapping)
                seen_spacy_keys.add(key)

        if profile.llm_prompt_context:
            llm_contexts.append(profile.llm_prompt_context)

    merged_names = [p.name for p in profiles]
    return ComplianceProfile(
        name="+".join(merged_names),
        display_name=" + ".join(p.display_name for p in profiles),
        description=f"Merged profile: {', '.join(merged_names)}",
        categories=all_categories,
        patterns=all_patterns,
        spacy_mappings=all_spacy_mappings,
        llm_prompt_context="\n\n".join(llm_contexts),
    )
