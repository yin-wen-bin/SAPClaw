from __future__ import annotations

import json

from sap_odata_agent.domain.models import QueryPlan
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.knowledge_graph.builder import build_local_knowledge_graph
from sap_odata_agent.infrastructure.knowledge_graph.provider import KnowledgeGraphProvider
from sap_odata_agent.infrastructure.llm.api_router import LlmApiRouter
from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent


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
                "### Unreceived Purchase Orders",
                "- Query `A_PurchaseOrderItem`.",
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
    candidate_facts = json.loads((output_root / "candidate_kg_facts.json").read_text(encoding="utf-8"))
    assert candidate_facts[0]["confirmed"] is False
    assert candidate_facts[0]["blocking"] is False


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


def test_result_verifier_blocks_confirmed_kg_warning_but_not_candidate() -> None:
    verifier = LlmResultVerifierAgent(llm_client=None, enabled=False)
    plan = QueryPlan(service_name="API_TEST_SRV", entity_set="A_PurchaseOrderItem")
    schema_context = {
        "available_fields": [
            {"entity_set": "A_PurchaseOrderItem", "field_name": "IsCompletelyDelivered"},
        ],
        "kg_semantic_warnings": [
            {
                "code": "kg_semantic_warning",
                "message": "Use completion status instead.",
                "blocking": True,
                "confirmed": True,
                "repair_hints": {
                    "preferred_select_fields": ["IsCompletelyDelivered", "NotInSchema"],
                    "preferred_filters": [
                        {
                            "entity_set": "A_PurchaseOrderItem",
                            "field": "IsCompletelyDelivered",
                            "operator": "eq",
                            "value": False,
                        },
                        {
                            "entity_set": "A_PurchaseOrderItem",
                            "field": "NotInSchema",
                            "operator": "eq",
                            "value": False,
                        },
                    ],
                },
            }
        ],
    }

    blocked = verifier.verify(_request("show unreceived orders"), plan, {"results": [{}]}, schema_context_summary=schema_context)

    assert blocked["passed"] is False
    assert blocked["source"] == "local_kg_result_verifier"
    assert blocked["repair_hints"]["preferred_select_fields"] == ["IsCompletelyDelivered"]
    assert [item["field"] for item in blocked["repair_hints"]["preferred_filters"]] == ["IsCompletelyDelivered"]

    schema_context["kg_semantic_warnings"][0]["confirmed"] = False
    candidate = verifier.verify(_request("show unreceived orders"), plan, {"results": [{}]}, schema_context_summary=schema_context)

    assert candidate["passed"] is True


def test_router_fallback_uses_kg_evidence_without_bypassing_routable_filter() -> None:
    router = LlmApiRouter(llm_client=None, enabled=False, allow_default_fallback=False)
    catalog = [
        {
            "service_name": "API_BLOCKED_SRV",
            "runtime_available": False,
            "kg_api_evidence": {
                "matched_terms": ["未清应付款"],
                "reason": "Strong but not routable",
                "evidence_text": "未清应付款",
            },
        },
        {
            "service_name": "API_GLACCOUNTLINEITEM",
            "runtime_available": True,
            "odata_runtime_available": True,
            "short_description": "",
            "primary_business_objects": [],
            "top_entities": [],
            "top_filter_fields": [],
            "top_answer_fields": [],
            "kg_api_evidence": {
                "matched_terms": ["未清应付款"],
                "reason": "Open AP line items",
                "evidence_text": "未清应付款 open supplier payable",
            },
        },
    ]

    decision = router.route("供应商是否有未清的应付款", catalog)

    assert decision.selected_apis
    assert decision.selected_apis[0].service_name == "API_GLACCOUNTLINEITEM"


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


def _request(text: str):
    from sap_odata_agent.domain.models import AgentRequest

    return AgentRequest(user_input=text)
