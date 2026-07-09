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
    assert skill.summary.startswith("## Business Semantics") or skill.summary.startswith("## Common Planning Patterns")
    assert "Open means" in skill.summary
    assert "Use this API for test documents" in skill.summary
    assert "Needs Verification" not in skill.summary
    assert skill.routing_hints.route_when == ["Query test documents by status."]
    assert skill.routing_hints.business_terms == ["Open means `IsClosed eq false`."]
    assert skill.routing_hints.route_not_when == ["Do not use expected flags as completion status."]
    assert skill.routing_hints.anti_patterns == ["Do not use expected flags as completion status."]


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
    assert enriched[0]["api_skill_routing_hints"] == {
        "route_when": [],
        "route_not_when": [],
        "business_terms": [],
        "anchor_terms": [],
        "companion_apis": [],
        "anti_patterns": [],
    }
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


def test_api_skill_provider_prioritizes_common_planning_patterns_before_truncation(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "skill.md").write_text(
        """# API_TEST Skill

## Purpose
{}

## When To Use
- Query this API.

## Business Semantics
- Basic semantics.

## Common Planning Patterns
- For line items with functional area, filter `FunctionalArea ne ''`.

## Pitfalls
- Do not use blank fields as negative proof.
""".format("x" * 1000),
        encoding="utf-8",
    )

    provider = ApiSkillProvider(skill_root=tmp_path, max_summary_chars=220)
    skill = provider.load("API_TEST")

    assert skill is not None
    assert skill.summary.startswith("## Common Planning Patterns")
    assert "FunctionalArea ne ''" in skill.summary


def test_api_skill_provider_extracts_structured_hints_and_companion_apis(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "skill.md").write_text(
        """# API_TEST Skill

## When To Use
- Use this API for product master queries by plant.

## When Not To Use
- Do not use this API for purchase orders; route to `API_PURCHASEORDER_PROCESS_SRV`.

## Business Semantics
- Batch managed wording belongs to product plant data.

## Common Planning Patterns
- For supplier contact enrichment, use `API_BUSINESS_PARTNER`.

## Pitfalls
- Do not use stock quantity wording here.
""",
        encoding="utf-8",
    )

    skill = ApiSkillProvider(skill_root=tmp_path).load("API_TEST")

    assert skill is not None
    assert skill.routing_hints.route_when == ["Use this API for product master queries by plant."]
    assert skill.routing_hints.route_not_when == [
        "Do not use this API for purchase orders; route to `API_PURCHASEORDER_PROCESS_SRV`.",
        "Do not use stock quantity wording here.",
    ]
    assert skill.routing_hints.business_terms == ["Batch managed wording belongs to product plant data."]
    assert skill.routing_hints.anchor_terms == ["For supplier contact enrichment, use `API_BUSINESS_PARTNER`."]
    assert skill.routing_hints.companion_apis == [
        "API_PURCHASEORDER_PROCESS_SRV",
        "API_BUSINESS_PARTNER",
    ]
    assert skill.routing_hints.anti_patterns == [
        "Do not use this API for purchase orders; route to `API_PURCHASEORDER_PROCESS_SRV`.",
        "Do not use stock quantity wording here.",
    ]


def test_api_skill_provider_missing_sections_emit_empty_hint_lists(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "skill.md").write_text(
        """# API_TEST Skill

## Purpose
Only purpose text.
""",
        encoding="utf-8",
    )

    skill = ApiSkillProvider(skill_root=tmp_path).load("API_TEST")

    assert skill is not None
    assert skill.routing_hints.as_dict() == {
        "route_when": [],
        "route_not_when": [],
        "business_terms": [],
        "anchor_terms": [],
        "companion_apis": [],
        "anti_patterns": [],
    }
