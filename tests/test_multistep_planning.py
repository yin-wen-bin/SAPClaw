import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, RetrievedContext, RetrievedDocument
from sap_odata_agent.infrastructure.llm.planner import RetrievalAwareIntentPlanner


def _write_index_fixture(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True, exist_ok=True)
    (service_dir / "services.json").write_text(json.dumps([{"service_name": "API_TEST"}]), encoding="utf-8")
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "key_fields": ["Supplier"],
                    "default_select_fields": ["Supplier"],
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "Supplier"],
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "key_fields": ["BusinessPartner", "AddressID"],
                    "default_select_fields": ["BusinessPartner", "PostalCode", "CityName"],
                    "supported_methods": ["GET"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {"service_name": "API_TEST", "entity_set": "A_Supplier", "field_name": "Supplier", "business_aliases": []},
                {"service_name": "API_TEST", "entity_set": "A_BusinessPartner", "field_name": "Supplier", "business_aliases": []},
                {"service_name": "API_TEST", "entity_set": "A_BusinessPartner", "field_name": "BusinessPartner", "business_aliases": []},
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "BusinessPartner",
                    "business_aliases": [],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "PostalCode",
                    "business_aliases": ["邮编", "邮政编码", "postal code"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "CityName",
                    "business_aliases": ["城市"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "entity_graph.json").write_text("[]", encoding="utf-8")
    (service_dir / "lookup_paths.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_planner_emits_multi_step_plan_for_postal_code_lookup(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="lookup-path-vector",
                title="supplier_to_postal_code",
                content="Resolve supplier to business partner, then read postal code.",
                score=18.0,
                metadata={
                    "path_id": "supplier_to_postal_code",
                    "anchor_object": "Supplier",
                    "target_entity_set": "A_BusinessPartnerAddress",
                    "target_field": "PostalCode",
                    "description": "Resolve supplier to business partner address postal code.",
                    "steps": [
                        {
                            "step_id": "resolve_business_partner",
                            "entity_set": "A_BusinessPartner",
                            "filter_field": "Supplier",
                            "select_fields": ["BusinessPartner", "Supplier"],
                            "top": 1,
                        },
                        {
                            "step_id": "fetch_address",
                            "entity_set": "A_BusinessPartnerAddress",
                            "filter_field": "BusinessPartner",
                            "select_fields": ["BusinessPartner", "PostalCode", "CityName"],
                            "top": 5,
                        },
                    ],
                },
            )
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商643266的邮编是多少？"), context)

    assert plan.plan_kind == "multi_step"
    assert plan.path_id == "supplier_to_postal_code"
    assert plan.target_field == "PostalCode"
    assert len(plan.steps) == 2
    assert plan.steps[0].entity_set == "A_BusinessPartner"
    assert plan.steps[0].filters[0].field == "Supplier"
    assert plan.steps[1].entity_set == "A_BusinessPartnerAddress"
    assert plan.steps[1].filter_from_previous[0].source_step_id == "resolve_business_partner"
    assert plan.steps[1].filter_from_previous[0].source_field == "BusinessPartner"
