import pytest

from delere.profiles.loader import (
    ComplianceProfile,
    list_profiles,
    load_profile,
    load_profiles,
    merge_profiles,
)


def test_list_profiles_includes_builtins():
    names = list_profiles()
    assert "pipeda" in names
    assert "gdpr" in names
    assert "hipaa" in names


def test_load_pipeda():
    profile = load_profile("pipeda")
    assert profile.name == "pipeda"
    assert profile.display_name == "PIPEDA (Canada)"
    assert len(profile.patterns) > 0
    assert len(profile.categories) > 0
    assert all(p.confidence > 0 for p in profile.patterns)


def test_load_gdpr():
    profile = load_profile("gdpr")
    assert profile.name == "gdpr"
    assert "national_id" in profile.categories
    assert "iban" in profile.categories


def test_load_hipaa():
    profile = load_profile("hipaa")
    assert profile.name == "hipaa"
    assert "ssn" in profile.categories
    assert "medical_record_number" in profile.categories


def test_all_profiles_have_spacy_mappings():
    for name in list_profiles():
        profile = load_profile(name)
        assert len(profile.spacy_mappings) > 0, f"{name} has no spaCy mappings"


def test_keyword_proximity_patterns_have_keywords():
    """Every pattern requiring keyword proximity must have at least one keyword."""
    for name in list_profiles():
        profile = load_profile(name)
        for p in profile.patterns:
            if p.requires_keyword_proximity:
                assert len(p.keywords) > 0, (
                    f"{name}/{p.name} requires keyword proximity but has no keywords"
                )


def test_invalid_profile_raises():
    with pytest.raises(FileNotFoundError, match="No compliance profile named"):
        load_profile("nonexistent")


def test_load_multiple_profiles():
    profiles = load_profiles(["pipeda", "gdpr"])
    assert len(profiles) == 2
    assert profiles[0].name == "pipeda"
    assert profiles[1].name == "gdpr"


def test_merge_deduplicates_patterns():
    profiles = load_profiles(["pipeda", "gdpr"])
    merged = merge_profiles(profiles)

    # email_address appears in both but should appear once after merge
    email_patterns = [p for p in merged.patterns if p.name == "email_address"]
    assert len(email_patterns) == 1


def test_merge_unions_categories():
    profiles = load_profiles(["pipeda", "hipaa"])
    merged = merge_profiles(profiles)

    # pipeda has "sin", hipaa has "ssn", merged should have both
    assert "sin" in merged.categories
    assert "ssn" in merged.categories


def test_merge_single_profile_returns_same():
    profile = load_profile("pipeda")
    merged = merge_profiles([profile])
    assert merged.name == profile.name
    assert merged.patterns == profile.patterns


def test_merge_joins_llm_context():
    profiles = load_profiles(["pipeda", "gdpr"])
    merged = merge_profiles(profiles)
    assert "PIPEDA" in merged.llm_prompt_context
    assert "GDPR" in merged.llm_prompt_context
