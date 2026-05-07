from pathlib import Path

from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider


def test_api_skill_provider_loads_and_summarizes_skill(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "skill.md").write_text(
        """# API_TEST Skill

## Purpose
Use this API for test documents.

## When To Use
- Query test documents by status.

## Business Semantics
- Open means `IsClosed eq false`.

## Pitfalls
- Do not use expected flags as completion status.

## Needs Verification
- Not part of router summary.
""",
        encoding="utf-8",
    )

    provider = ApiSkillProvider(skill_root=tmp_path)
    skill = provider.load("API_TEST")

    assert skill is not None
    assert skill.service_name == "API_TEST"
    assert "Use this API for test documents" in skill.content
    assert "Open means" in skill.summary
    assert "Needs Verification" not in skill.summary


def test_api_skill_provider_enriches_catalog_without_dropping_entries(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_WITH_SKILL"
    service_dir.mkdir(parents=True)
    (service_dir / "skill.md").write_text(
        """# API_WITH_SKILL Skill

## Purpose
Use this API for skilled routing.
""",
        encoding="utf-8",
    )

    catalog = [
        {"service_name": "API_WITH_SKILL", "short_description": "Has skill."},
        {"service_name": "API_NO_SKILL", "short_description": "No skill."},
    ]
    enriched = ApiSkillProvider(skill_root=tmp_path).enrich_catalog(catalog)

    assert enriched[0]["api_skill_summary"].startswith("## Purpose")
    assert "api_skill_summary" not in enriched[1]
    assert catalog[0].get("api_skill_summary") is None


def test_api_skill_provider_reuses_cache_until_skill_file_changes(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)
    skill_path = service_dir / "skill.md"
    skill_path.write_text(
        """# API_TEST Skill

## Purpose
Use first version.
""",
        encoding="utf-8",
    )

    provider = ApiSkillProvider(skill_root=tmp_path)
    first = provider.load("API_TEST")
    second = provider.load("API_TEST")

    assert first is not None
    assert second is first

    skill_path.write_text(
        """# API_TEST Skill

## Purpose
Use second version with changed length.
""",
        encoding="utf-8",
    )

    third = provider.load("API_TEST")

    assert third is not None
    assert third is not first
    assert "second version" in third.content
