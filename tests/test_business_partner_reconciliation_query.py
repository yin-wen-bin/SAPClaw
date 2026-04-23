import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor
from sap_odata_agent.infrastructure.llm.planner import RetrievalAwareIntentPlanner
from sap_odata_agent.infrastructure.llm.query_classifier import QueryShapeClassifier
from sap_odata_agent.infrastructure.retrieval.local_doc_retriever import LocalDocRetriever


def _write_json(path: Path, payload: list[dict]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_reconciliation_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    _write_json(
        service_dir / "services.json",
        [
            {
                "service_name": "API_TEST",
                "description": "Business partner service",
                "entity_sets": ["A_BusinessPartner", "A_SupplierCompany"],
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
                "default_select_fields": ["BusinessPartner", "Supplier"],
                "supported_methods": ["GET"],
                "description": "Business partner general data",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_SupplierCompany",
                "entity_type": "A_SupplierCompanyType",
                "key_fields": ["Supplier", "CompanyCode"],
                "default_select_fields": ["Supplier", "CompanyCode"],
                "supported_methods": ["GET"],
                "description": "Supplier company data",
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
                "label": "\u4e1a\u52a1\u4f19\u4f34",
                "description": "\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7",
                "business_aliases": ["\u4e1a\u52a1\u4f19\u4f34"],
                "filterable": True,
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "field_name": "Supplier",
                "label": "\u4f9b\u5e94\u5546",
                "description": "\u4f9b\u5e94\u5546\u7f16\u53f7",
                "business_aliases": ["\u4f9b\u5e94\u5546"],
                "filterable": True,
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_SupplierCompany",
                "field_name": "Supplier",
                "label": "\u4f9b\u5e94\u5546",
                "description": "\u4f9b\u5e94\u5546\u7f16\u53f7",
                "business_aliases": ["\u4f9b\u5e94\u5546"],
                "filterable": True,
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_SupplierCompany",
                "field_name": "CompanyCode",
                "label": "\u516c\u53f8\u4ee3\u7801",
                "description": "\u516c\u53f8\u4ee3\u7801",
                "business_aliases": ["\u516c\u53f8\u4ee3\u7801"],
                "filterable": True,
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_SupplierCompany",
                "field_name": "ReconciliationAccount",
                "label": "\u7edf\u9a6d\u79d1\u76ee",
                "description": "\u603b\u5e10\u4e2d\u7684\u7edf\u9a6d\u79d1\u76ee",
                "business_aliases": ["\u7edf\u9a6d\u79d1\u76ee"],
                "filterable": True,
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
        key = (str(metadata.get("entity_set", "")), str(metadata.get("field_name", "")))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        fields.append(metadata)
    return fields


def test_business_partner_alphanumeric_id_and_reconciliation_account_typo_plan(tmp_path: Path) -> None:
    _write_reconciliation_index(tmp_path)
    query = "\u4e1a\u52a1\u4f19\u4f34USSU-VSF54\u7684\u7edf\u5fa1\u79d1\u76ee\u662f\u4ec0\u4e48"
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

    assert constraints.target_object == "business_partner"
    assert constraints.target_field_concepts == []
    assert constraints.filter_values == ["USSU-VSF54"]
    assert plan.plan_kind == "direct"
    assert plan.filters[0].field == "BusinessPartner"
