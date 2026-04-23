import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor
from sap_odata_agent.infrastructure.llm.planner import RetrievalAwareIntentPlanner
from sap_odata_agent.infrastructure.llm.query_classifier import QueryShapeClassifier
from sap_odata_agent.infrastructure.retrieval.local_doc_retriever import LocalDocRetriever


def _write_json(path: Path, payload: list[dict]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_business_partner_customer_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)

    _write_json(
        service_dir / "services.json",
        [
            {
                "service_name": "API_TEST",
                "description": "Business partner and customer service",
                "entity_sets": ["A_BusinessPartner", "A_Customer"],
            }
        ],
    )
    _write_json(
        service_dir / "entities.json",
        [
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "entity_type": "A_BusinessPartnerType",
                "key_fields": ["BusinessPartner"],
                "default_select_fields": ["BusinessPartner", "Customer"],
                "supported_methods": ["GET"],
                "description": "Business partner general data",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_Customer",
                "entity_type": "A_CustomerType",
                "key_fields": ["Customer"],
                "default_select_fields": ["Customer", "CustomerAccountGroup"],
                "supported_methods": ["GET"],
                "description": "Customer general data",
            },
        ],
    )
    _write_json(
        service_dir / "fields.json",
        [
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "field_name": "BusinessPartner",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u4e1a\u52a1\u4f19\u4f34",
                "description": "\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7",
                "business_aliases": ["\u4e1a\u52a1\u4f19\u4f34"],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "field_name": "Customer",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u5ba2\u6237",
                "description": "\u5ba2\u6237\u7f16\u53f7",
                "business_aliases": ["\u5ba2\u6237"],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_Customer",
                "field_name": "Customer",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u5ba2\u6237",
                "description": "\u5ba2\u6237\u7f16\u53f7",
                "business_aliases": ["\u5ba2\u6237"],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_Customer",
                "field_name": "CustomerAccountGroup",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u5ba2\u6237\u79d1\u76ee\u7ec4",
                "description": "\u5ba2\u6237\u79d1\u76ee\u7ec4",
                "business_aliases": ["\u5ba2\u6237\u79d1\u76ee\u7ec4"],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_Supplier",
                "field_name": "SupplierAccountGroup",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u79d1\u76ee\u7ec4",
                "description": "\u4f9b\u5e94\u5546\u79d1\u76ee\u7ec4",
                "business_aliases": ["\u79d1\u76ee\u7ec4"],
            },
        ],
    )
    for filename in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        _write_json(service_dir / filename, [])
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def _candidate_fields(context) -> list[dict]:
    fields: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for document in context.documents:
        metadata = document.metadata or {}
        entity_set = str(metadata.get("entity_set", ""))
        field_name = str(metadata.get("field_name", ""))
        if not entity_set or not field_name:
            continue
        key = (entity_set, field_name)
        if key in seen:
            continue
        seen.add(key)
        fields.append(metadata)
    return fields


def test_business_partner_customer_number_and_account_group_constraints(tmp_path: Path) -> None:
    _write_business_partner_customer_index(tmp_path)
    query = "\u4e1a\u52a1\u4f19\u4f341000561\u7684\u5ba2\u6237\u7f16\u53f7\u548c\u5ba2\u6237\u79d1\u76ee\u7ec4\u662f\u4ec0\u4e48\uff1f"
    context = LocalDocRetriever(index_root=str(tmp_path), service_name="API_TEST").retrieve(query, top_k=12)
    query_shape, cardinality, _ = QueryShapeClassifier().classify(query)

    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=_candidate_fields(context),
    )

    assert constraints.target_object == "business_partner"
    assert set(constraints.target_field_concepts) == {"Customer", "CustomerAccountGroup"}
    assert constraints.filter_concepts == []
    assert constraints.filter_values == ["1000561"]


def test_business_partner_customer_number_and_account_group_uses_bridge(tmp_path: Path) -> None:
    _write_business_partner_customer_index(tmp_path)
    query = "\u4e1a\u52a1\u4f19\u4f341000561\u7684\u5ba2\u6237\u7f16\u53f7\u548c\u5ba2\u6237\u79d1\u76ee\u7ec4\u662f\u4ec0\u4e48\uff1f"
    context = LocalDocRetriever(index_root=str(tmp_path), service_name="API_TEST").retrieve(query, top_k=12)
    query_shape, cardinality, _ = QueryShapeClassifier().classify(query)
    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=_candidate_fields(context),
    )

    plan = RetrievalAwareIntentPlanner(index_root=str(tmp_path), service_name="API_TEST").plan(
        AgentRequest(
            user_input=query,
            query_shape=query_shape,
            cardinality_policy=cardinality,
            constraints=constraints,
        ),
        context,
    )

    assert plan.plan_kind == "multi_step"
    assert plan.entity_set == "A_Customer"
    assert plan.steps[0].entity_set == "A_BusinessPartner"
    assert [(item.field, item.operator, item.value) for item in plan.steps[0].filters] == [
        ("BusinessPartner", "eq", "1000561")
    ]
    assert plan.steps[1].entity_set == "A_Customer"
    assert plan.steps[1].filter_from_previous[0].source_field == "Customer"
    assert "Customer" in plan.steps[1].select_fields
    assert "CustomerAccountGroup" in plan.steps[1].select_fields
