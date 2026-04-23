import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, FilterCondition, QueryPlan, RetrievedContext, RetrievedDocument
from sap_odata_agent.infrastructure.llm.planner import IndexAwareRepairEngine


def _write_repair_fixture(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "description": "Business partner service",
                    "entity_sets": ["A_BusinessPartner", "A_Customer"],
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
                    "entity_set": "A_BusinessPartner",
                    "entity_type": "A_BusinessPartnerType",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName", "Customer"],
                    "supported_methods": ["GET", "PATCH"],
                    "description": "Business partner header data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Customer",
                    "entity_type": "A_CustomerType",
                    "key_fields": ["Customer"],
                    "default_select_fields": ["Customer", "CustomerFullName", "BPCustomerFullName"],
                    "supported_methods": ["GET"],
                    "description": "Customer header data",
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
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartner",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Business partner number",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartnerFullName",
                    "data_type": "Edm.String",
                    "filterable": False,
                    "sortable": True,
                    "description": "Business partner full name",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Customer",
                    "field_name": "Customer",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Customer number",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Customer",
                    "field_name": "CustomerFullName",
                    "data_type": "Edm.String",
                    "filterable": False,
                    "sortable": True,
                    "description": "Customer full name",
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text("[]", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_repair_engine_removes_invalid_select_field(tmp_path: Path) -> None:
    _write_repair_fixture(tmp_path)
    engine = IndexAwareRepairEngine(index_root=tmp_path, service_name="API_TEST")
    previous_plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Customer",
        select_fields=["Customer", "BadField", "CustomerFullName"],
        filters=[FilterCondition(field="Customer", operator="eq", value="300001")],
    )

    repaired = engine.repair(
        request=AgentRequest(user_input="查询客户300001的基本信息"),
        context=RetrievedContext(documents=[]),
        previous_plan=previous_plan,
        error_message="找不到细分 'BadField' 的资源。",
    )

    assert "BadField" not in repaired.select_fields
    assert repaired.entity_set == "A_Customer"


def test_repair_engine_switches_entity_for_invalid_filter_field(tmp_path: Path) -> None:
    _write_repair_fixture(tmp_path)
    engine = IndexAwareRepairEngine(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_BusinessPartner",
                content="Likely entity candidate",
                score=10.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                    "supported_methods": ["GET", "PATCH"],
                    "description": "Business partner header data",
                },
            )
        ]
    )
    previous_plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Customer",
        select_fields=["Customer", "CustomerFullName"],
        filters=[FilterCondition(field="BusinessPartner", operator="eq", value="300001")],
    )

    repaired = engine.repair(
        request=AgentRequest(user_input="查询业务伙伴300001的基本信息"),
        context=context,
        previous_plan=previous_plan,
        error_message="Property BusinessPartner not found in type A_CustomerType",
    )

    assert repaired.entity_set == "A_BusinessPartner"
    assert repaired.filters[0].field == "BusinessPartner"
    assert "BusinessPartnerFullName" in repaired.select_fields
