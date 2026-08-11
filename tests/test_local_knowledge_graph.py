from __future__ import annotations

import json

from sap_odata_agent.domain.models import ExecutionStep, QueryPlan
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.knowledge_graph.builder import build_local_knowledge_graph
from sap_odata_agent.infrastructure.knowledge_graph.provider import KnowledgeGraphProvider


def test_local_kg_builder_creates_confirmed_and_candidate_facts(tmp_path) -> None:
    index_root = tmp_path / "index"
    skill_root = tmp_path / "api_skills"
    output_root = tmp_path / "knowledge_graph"
    service_dir = index_root / "API_TEST_SRV"
    service_dir.mkdir(parents=True)
    _write_json(
        service_dir / "services.json",
        [
            {
                "service_name": "API_TEST_SRV",
                "description": "Purchase order test API",
                "entity_sets": ["A_PurchaseOrderItem"],
                "runtime_available": True,
                "odata_runtime_available": True,
            }
        ],
    )
    _write_json(
        service_dir / "fields.json",
        [
            {
                "service_name": "API_TEST_SRV",
                "entity_set": "A_PurchaseOrderItem",
                "field_name": "GoodsReceiptIsExpected",
                "label": "Goods receipt expected",
                "business_aliases": ["needs goods receipt"],
                "data_type": "Edm.Boolean",
                "filterable": True,
            },
            {
                "service_name": "API_TEST_SRV",
                "entity_set": "A_PurchaseOrderItem",
                "field_name": "IsCompletelyDelivered",
                "label": "Completely delivered",
                "data_type": "Edm.Boolean",
                "filterable": True,
            },
        ],
    )
    _write_json(
        service_dir / "relations.json",
        [
            {
                "service_name": "API_TEST_SRV",
                "from_entity_set": "A_PurchaseOrder",
                "to_entity_set": "A_PurchaseOrderItem",
                "navigation_name": "to_PurchaseOrderItem",
            }
        ],
    )
    skill_dir = skill_root / "API_TEST_SRV"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "\n".join(
            [
                "# API_TEST_SRV",
                "Use this API for purchase order and unreceived order questions.",
                "Do not use `A_PurchaseOrderItem.GoodsReceiptIsExpected` alone to prove unreceived purchase orders.",
                "Prefer `A_PurchaseOrderItem.IsCompletelyDelivered` for actual delivery completion.",
                "## Common Planning Patterns",
                "### Unreceived Purchase Orders Planning Pattern",
                "- Query `A_PurchaseOrderItem` and `API_COMPANION_SRV.A_Companion`.",
                "- Filter `GoodsReceiptIsExpected` eq true.",
                "- Filter `IsCompletelyDelivered` eq false.",
            ]
        ),
        encoding="utf-8",
    )
    feedback_path = tmp_path / "feedback_memory.jsonl"
    feedback_path.write_text(
        json.dumps({"lesson": "Use API_TEST_SRV for unreceived orders"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = build_local_knowledge_graph(
        index_root=index_root,
        api_skill_root=skill_root,
        output_root=output_root,
        feedback_memory_path=feedback_path,
        include_feedback=True,
    )

    assert summary["counts"]["api_candidates"] == 1
    assert summary["counts"]["candidate_kg_facts"] == 1
    field_semantics = json.loads((output_root / "field_semantics.json").read_text(encoding="utf-8"))
    assert any(item["field_name"] == "GoodsReceiptIsExpected" and item["confirmed"] for item in field_semantics)
    business_paths = json.loads((output_root / "business_paths.json").read_text(encoding="utf-8"))
    path = next(item for item in business_paths if item["intent"] == "Unreceived Purchase Orders Planning Pattern")
    assert path["service_names"] == ["API_TEST_SRV", "API_COMPANION_SRV"]
    candidate_facts = json.loads((output_root / "candidate_kg_facts.json").read_text(encoding="utf-8"))
    assert candidate_facts[0]["confirmed"] is False
    assert candidate_facts[0]["blocking"] is False


def test_local_kg_builder_only_blocks_negated_field_refs(tmp_path) -> None:
    index_root = tmp_path / "index"
    skill_root = tmp_path / "api_skills"
    output_root = tmp_path / "knowledge_graph"
    service_dir = index_root / "API_SUPPLIER_TEST"
    service_dir.mkdir(parents=True)
    _write_json(
        service_dir / "services.json",
        [
            {
                "service_name": "API_SUPPLIER_TEST",
                "description": "Supplier test API",
                "entity_sets": ["A_Supplier"],
                "runtime_available": True,
                "odata_runtime_available": True,
            }
        ],
    )
    _write_json(
        service_dir / "fields.json",
        [
            {"service_name": "API_SUPPLIER_TEST", "entity_set": "A_Supplier", "field_name": "Supplier"},
            {"service_name": "API_SUPPLIER_TEST", "entity_set": "A_Supplier", "field_name": "SupplierName"},
            {"service_name": "API_SUPPLIER_TEST", "entity_set": "A_Supplier", "field_name": "PurchasingIsBlocked"},
        ],
    )
    _write_json(service_dir / "relations.json", [])
    skill_dir = skill_root / "API_SUPPLIER_TEST"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        (
            "Use `A_Supplier.Supplier` and `A_Supplier.SupplierName` for supplier basic information, "
            "but do not use `A_Supplier.PurchasingIsBlocked` to answer supplier profile questions."
        ),
        encoding="utf-8",
    )

    build_local_knowledge_graph(index_root=index_root, api_skill_root=skill_root, output_root=output_root)

    field_semantics = json.loads((output_root / "field_semantics.json").read_text(encoding="utf-8"))
    blocking_by_field = {
        item["field_name"]: item["blocking"]
        for item in field_semantics
        if item["service_name"] == "API_SUPPLIER_TEST"
    }
    assert blocking_by_field["Supplier"] is False
    assert blocking_by_field["SupplierName"] is False
    assert blocking_by_field["PurchasingIsBlocked"] is True


def test_knowledge_graph_provider_can_be_disabled(tmp_path) -> None:
    provider = KnowledgeGraphProvider(tmp_path / "missing", enabled=False)

    assert provider.recommend_apis("anything") == []
    assert provider.recommend_fields("anything", "API_TEST_SRV") == []
    assert provider.recommend_paths("anything", ["API_TEST_SRV"]) == []


def test_knowledge_graph_provider_returns_confirmed_semantic_warning(tmp_path) -> None:
    kg_root = tmp_path / "kg"
    kg_root.mkdir()
    _write_json(kg_root / "business_terms.json", [])
    _write_json(kg_root / "business_paths.json", [])
    _write_json(kg_root / "api_candidates.json", [])
    _write_json(kg_root / "candidate_kg_facts.json", [])
    _write_json(kg_root / "build_summary.json", {"build_version": "test"})
    _write_json(
        kg_root / "field_semantics.json",
        [
            {
                "service_name": "API_TEST_SRV",
                "entity_set": "A_PurchaseOrderItem",
                "field_name": "GoodsReceiptIsExpected",
                "does_not_support": ["unreceived purchase orders"],
                "blocking": True,
                "confirmed": True,
                "confidence": 0.9,
                "evidence_text": "GoodsReceiptIsExpected alone does not prove unreceived purchase orders.",
                "repair_hints": {
                    "preferred_select_fields": ["IsCompletelyDelivered"],
                    "preferred_filters": [
                        {
                            "entity_set": "A_PurchaseOrderItem",
                            "field": "IsCompletelyDelivered",
                            "operator": "eq",
                            "value": False,
                            "value_type": "boolean",
                        }
                    ],
                },
            }
        ],
    )
    provider = KnowledgeGraphProvider(kg_root)
    plan = QueryPlan(
        service_name="API_TEST_SRV",
        entity_set="A_PurchaseOrderItem",
        select_fields=["PurchaseOrder", "GoodsReceiptIsExpected"],
    )

    warnings = provider.semantic_warnings("show unreceived purchase orders", plan)

    assert warnings
    assert warnings[0]["blocking"] is True
    assert warnings[0]["confirmed"] is True


def test_knowledge_graph_provider_matches_warning_entity_and_field(tmp_path) -> None:
    kg_root = tmp_path / "kg"
    kg_root.mkdir()
    _write_json(kg_root / "business_terms.json", [])
    _write_json(kg_root / "business_paths.json", [])
    _write_json(kg_root / "api_candidates.json", [])
    _write_json(kg_root / "candidate_kg_facts.json", [])
    _write_json(kg_root / "build_summary.json", {"build_version": "test"})
    _write_json(
        kg_root / "field_semantics.json",
        [
            {
                "service_name": "API_STOCK_TEST",
                "entity_set": "A_MatlStkInAcctMod",
                "field_name": "Batch",
                "does_not_support": ["material-level stock"],
                "blocking": True,
                "confirmed": True,
                "confidence": 0.9,
                "evidence_text": "A_MatlStkInAcctMod.Batch does not support material-level stock.",
            }
        ],
    )
    provider = KnowledgeGraphProvider(kg_root)
    unrelated_plan = QueryPlan(
        service_name="API_STOCK_TEST",
        entity_set="A_MaterialSerialNumber",
        select_fields=["Batch"],
    )
    matching_step_plan = QueryPlan(
        service_name="API_STOCK_TEST",
        entity_set="A_Material",
        steps=[
            ExecutionStep(
                step_id="step_1",
                service_name="API_STOCK_TEST",
                entity_set="A_MatlStkInAcctMod",
                select_fields=["Material", "Batch"],
            )
        ],
    )

    assert provider.semantic_warnings("show material-level stock", unrelated_plan) == []
    warnings = provider.semantic_warnings("show material-level stock", matching_step_plan)
    assert warnings
    assert warnings[0]["entity_set"] == "A_MatlStkInAcctMod"


def test_schema_context_summary_preserves_optional_kg_fields() -> None:
    context = {
        "service_name": "API_TEST_SRV",
        "candidate_fields": [],
        "entities": [],
        "kg_business_terms": [{"term": "未清应付款"}],
        "kg_recommended_fields": [{"field_name": "OpenItem"}],
        "kg_recommended_paths": [{"intent": "AP open items"}],
        "kg_semantic_warnings": [{"code": "test"}],
        "kg_debug": {
            "kg_enabled": True,
            "kg_build_version": "test",
            "kg_evidence_used": [{"service_name": "API_TEST_SRV"}],
        },
    }

    summary = SchemaContextProvider.summarize(context)

    assert summary["kg_enabled"] is True
    assert summary["kg_business_terms"][0]["term"] == "未清应付款"
    assert summary["kg_build_version"] == "test"


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
