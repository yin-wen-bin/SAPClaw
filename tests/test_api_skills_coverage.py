from __future__ import annotations

import json
import re
from pathlib import Path

from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_ROOT = REPO_ROOT / "data" / "index"
SKILL_ROOT = REPO_ROOT / "data" / "api_skills"
REQUIRED_SECTIONS = [
    "Purpose",
    "When To Use",
    "When Not To Use",
    "Key Entities",
    "Business Semantics",
    "Common Planning Patterns",
    "Pitfalls",
    "Needs Verification",
]


def _indexed_apis() -> list[str]:
    return sorted(path.name for path in INDEX_ROOT.iterdir() if (path / "entities.json").exists())


def _load_entity_fields(api_name: str) -> tuple[set[str], dict[str, set[str]]]:
    entities = json.loads((INDEX_ROOT / api_name / "entities.json").read_text(encoding="utf-8"))
    entity_names = {entity["entity_set"] for entity in entities}

    fields: dict[str, set[str]] = {name: set() for name in entity_names}
    fields_path = INDEX_ROOT / api_name / "fields.json"
    if fields_path.exists():
        for field in json.loads(fields_path.read_text(encoding="utf-8")):
            entity_set = field.get("entity_set")
            field_name = field.get("field_name")
            if entity_set in fields and field_name:
                fields[entity_set].add(field_name)
    for entity in entities:
        entity_set = entity["entity_set"]
        fields[entity_set].update(entity.get("key_fields", []))
        fields[entity_set].update(entity.get("default_select_fields", []))
    return entity_names, fields


def test_each_indexed_api_has_skill_with_required_sections() -> None:
    missing: list[str] = []
    for api_name in _indexed_apis():
        skill_path = SKILL_ROOT / api_name / "skill.md"
        if not skill_path.exists():
            missing.append(api_name)
            continue
        content = skill_path.read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            assert f"## {section}" in content, f"{api_name} skill missing section: {section}"

    assert missing == []


def test_api_skill_entity_references_match_index() -> None:
    for api_name in _indexed_apis():
        entity_names, fields_by_entity = _load_entity_fields(api_name)
        content = (SKILL_ROOT / api_name / "skill.md").read_text(encoding="utf-8")

        for reference in re.findall(r"`([^`]+)`", content):
            if not reference.startswith("A_"):
                continue
            if not re.fullmatch(r"A_[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?", reference):
                continue
            if "." not in reference:
                assert reference in entity_names, f"{api_name} skill references unknown entity {reference}"
                continue
            entity_set, field_name = reference.split(".", 1)
            assert entity_set in entity_names, f"{api_name} skill references unknown entity {entity_set}"
            assert (
                field_name in fields_by_entity[entity_set]
            ), f"{api_name} skill references unknown field {reference}"


def test_api_skill_provider_loads_all_indexed_skills() -> None:
    provider = ApiSkillProvider(skill_root=str(SKILL_ROOT))
    for api_name in _indexed_apis():
        skill = provider.load(api_name)
        assert skill is not None
        assert skill.service_name == api_name
        assert skill.summary


def test_product_skill_guides_tax_classification_to_sales_tax_entity() -> None:
    content = (SKILL_ROOT / "API_PRODUCT_SRV" / "skill.md").read_text(encoding="utf-8")

    assert "`A_ProductSalesTax.TaxClassification`" in content
    assert "`A_ProductSales.TaxClassification`" in content
    assert "Do not answer \"not maintained\" from blank `A_ProductSales.TaxClassification`" in content


def test_purchase_order_skill_disambiguates_history_from_pricing() -> None:
    content = (SKILL_ROOT / "API_PURCHASEORDER_PROCESS_SRV" / "skill.md").read_text(encoding="utf-8")

    assert "Purchase Order History Wording" in content
    assert "`A_PurOrdPricingElement` contains pricing condition lines only" in content
    assert "Do not label `A_PurOrdPricingElement` results as purchase order history" in content
