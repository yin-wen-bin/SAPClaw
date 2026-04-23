import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, QueryConstraints, QueryPlan, QueryShape
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor
from sap_odata_agent.infrastructure.llm.planner import IndexAwareRepairEngine, RetrievalAwareIntentPlanner
from sap_odata_agent.infrastructure.llm.query_classifier import QueryShapeClassifier
from sap_odata_agent.infrastructure.retrieval.local_doc_retriever import LocalDocRetriever


def _write_partner_function_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_sets": ["A_CustSalesPartnerFunc", "A_SupplierPartnerFunc", "A_Supplier"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustSalesPartnerFunc",
                    "key_fields": ["Customer", "SalesOrganization", "PartnerFunction", "PartnerCounter"],
                    "default_select_fields": [
                        "Customer",
                        "SalesOrganization",
                        "PartnerFunction",
                        "PartnerCounter",
                        "Supplier",
                    ],
                    "description": "Retrieves customer sales area partner function records.",
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "key_fields": [
                        "Supplier",
                        "PurchasingOrganization",
                        "PartnerFunction",
                        "PartnerCounter",
                    ],
                    "default_select_fields": [
                        "Supplier",
                        "PurchasingOrganization",
                        "PartnerFunction",
                        "PartnerCounter",
                        "DefaultPartner",
                    ],
                    "description": "Retrieves supplier purchasing organization partner function records.",
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "key_fields": ["Supplier"],
                    "default_select_fields": ["Supplier", "SupplierName"],
                    "description": "Retrieves supplier master data.",
                    "supported_methods": ["GET"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustSalesPartnerFunc",
                    "field_name": "Customer",
                    "filterable": True,
                    "label": "客户",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustSalesPartnerFunc",
                    "field_name": "Supplier",
                    "filterable": True,
                    "label": "供应商",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustSalesPartnerFunc",
                    "field_name": "PartnerFunction",
                    "filterable": True,
                    "label": "合作伙伴职能",
                    "description": "合作伙伴职能",
                    "business_aliases": ["合作伙伴职能"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "field_name": "Supplier",
                    "filterable": True,
                    "label": "供应商",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "field_name": "PurchasingOrganization",
                    "filterable": True,
                    "label": "采购组织",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "field_name": "PartnerFunction",
                    "filterable": True,
                    "label": "合作伙伴职能",
                    "description": "合作伙伴职能",
                    "business_aliases": ["合作伙伴职能"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "field_name": "Supplier",
                    "filterable": True,
                    "label": "供应商",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "field_name": "SupplierName",
                    "filterable": False,
                    "label": "供应商名称",
                },
            ]
        ),
        encoding="utf-8",
    )
    for name in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / name).write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_partner_function_query_uses_fuzzy_metadata_label_and_supplier_entity(tmp_path: Path) -> None:
    _write_partner_function_index(tmp_path)
    query = "供应商17300003的合作伙伴功能有哪些？"
    retriever = LocalDocRetriever(index_root=tmp_path, service_name="API_TEST")
    context = retriever.retrieve(query, top_k=8)

    assert any(
        document.source == "field-fuzzy"
        and (document.metadata or {}).get("entity_set") == "A_SupplierPartnerFunc"
        and (document.metadata or {}).get("field_name") == "PartnerFunction"
        for document in context.documents
    )

    query_shape, cardinality, _ = QueryShapeClassifier().classify(query)
    candidate_fields = [
        document.metadata
        for document in context.documents
        if (document.metadata or {}).get("entity_set") and (document.metadata or {}).get("field_name")
    ]
    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=candidate_fields,
    )

    assert constraints.target_object == "supplier"
    assert constraints.target_field_concepts == ["PartnerFunction"]

    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    plan = planner.plan(
        AgentRequest(
            user_input=query,
            query_shape=query_shape,
            cardinality_policy=cardinality,
            constraints=constraints,
        ),
        context,
    )

    assert plan.entity_set == "A_SupplierPartnerFunc"
    assert "PartnerFunction" in plan.select_fields
    assert plan.filters[0].field == "Supplier"
    assert plan.filters[0].value == "17300003"


def test_repair_infers_anchor_filter_when_wrong_entity_has_same_target_field(tmp_path: Path) -> None:
    _write_partner_function_index(tmp_path)
    engine = IndexAwareRepairEngine(index_root=tmp_path, service_name="API_TEST")
    request = AgentRequest(
        user_input="供应商17300003的合作伙伴功能有哪些？",
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            target_object="supplier",
            target_field_concepts=["PartnerFunction"],
            filter_concepts=[],
            filter_values=["17300003"],
        ),
    )
    bad_plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Supplier",
        select_fields=["Supplier", "SupplierName"],
        filters=[],
        rationale="Wrong entity selected.",
    )

    repaired = engine.repair(
        request,
        context=None,
        previous_plan=bad_plan,
        error_message="llm_wrong_entity_for_target",
    )

    assert repaired.entity_set == "A_SupplierPartnerFunc"
    assert "PartnerFunction" in repaired.select_fields
    assert repaired.filters[0].field == "Supplier"
    assert repaired.filters[0].value == "17300003"
