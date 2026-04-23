import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, CardinalityPolicy, QueryShape
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor
from sap_odata_agent.infrastructure.llm.planner import RetrievalAwareIntentPlanner
from sap_odata_agent.infrastructure.llm.query_classifier import QueryShapeClassifier
from sap_odata_agent.infrastructure.retrieval.local_doc_retriever import LocalDocRetriever


def _write_json(path: Path, payload: list[dict]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_customer_sales_area_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)

    _write_json(
        service_dir / "services.json",
        [
            {
                "service_name": "API_TEST",
                "description": "Business partner service",
                "entity_sets": [
                    "A_BusinessPartner",
                    "A_Customer",
                    "A_CustomerSalesArea",
                    "A_CustSalesPartnerFunc",
                    "A_BusinessPartnerAddress",
                ],
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
                "default_select_fields": ["Customer", "BusinessPartner"],
                "supported_methods": ["GET"],
                "description": "Customer general data",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustomerSalesArea",
                "entity_type": "A_CustomerSalesAreaType",
                "key_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division"],
                "default_select_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division"],
                "supported_methods": ["GET"],
                "description": "Customer sales area data",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustSalesPartnerFunc",
                "entity_type": "A_CustSalesPartnerFuncType",
                "key_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division", "PartnerCounter"],
                "default_select_fields": [
                    "Customer",
                    "SalesOrganization",
                    "DistributionChannel",
                    "Division",
                    "PartnerCounter",
                ],
                "supported_methods": ["GET"],
                "description": "Customer sales partner function data",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartnerAddress",
                "entity_type": "A_BusinessPartnerAddressType",
                "key_fields": ["BusinessPartner", "AddressID"],
                "default_select_fields": ["BusinessPartner", "AddressID", "Region"],
                "supported_methods": ["GET"],
                "description": "Business partner address data",
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
                "description": "Business partner number",
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
                "description": "Customer number",
                "business_aliases": ["\u5ba2\u6237"],
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
                "field_name": "BusinessPartner",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "Business partner number",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustomerSalesArea",
                "field_name": "Customer",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "Customer number",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustomerSalesArea",
                "field_name": "SalesOrganization",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u9500\u552e\u7ec4\u7ec7",
                "description": "Sales organization",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustomerSalesArea",
                "field_name": "DistributionChannel",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "Distribution channel",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustomerSalesArea",
                "field_name": "Division",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "Division",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustomerSalesArea",
                "field_name": "SalesDistrict",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u9500\u552e\u5730\u533a",
                "description": "Sales district",
                "business_aliases": ["\u9500\u552e\u5730\u533a", "sales district"],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustSalesPartnerFunc",
                "field_name": "Customer",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "Customer number",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_CustSalesPartnerFunc",
                "field_name": "SalesOrganization",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u9500\u552e\u7ec4\u7ec7",
                "description": "Sales organization",
                "business_aliases": ["\u9500\u552e\u7ec4\u7ec7", "sales organization"],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "BusinessPartner",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "Business partner number",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "Region",
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "label": "\u5730\u533a",
                "description": "Region",
                "business_aliases": ["\u5730\u533a", "region"],
            },
        ],
    )
    _write_json(service_dir / "relations.json", [])
    _write_json(service_dir / "entity_graph.json", [])
    _write_json(service_dir / "lookup_paths.json", [])
    _write_json(service_dir / "business_terms.json", [])
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


def test_sales_district_is_not_shadowed_by_region(tmp_path: Path) -> None:
    _write_customer_sales_area_index(tmp_path)
    query = "\u5ba2\u62371000561\u7684\u9500\u552e\u5730\u533a\u662f\u4ec0\u4e48\uff1f"
    context = LocalDocRetriever(index_root=str(tmp_path), service_name="API_TEST").retrieve(query, top_k=12)
    query_shape, cardinality, _ = QueryShapeClassifier().classify(query)

    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=_candidate_fields(context),
    )

    assert constraints.target_object == "customer"
    assert constraints.target_field_concepts == ["SalesDistrict"]
    assert "Region" not in constraints.target_field_concepts
    assert constraints.filter_concepts == []
    assert constraints.filter_values == ["1000561"]


def test_metadata_label_drives_target_field_without_static_alias() -> None:
    query = "\u5ba2\u62371000561\u7684\u9500\u552e\u7247\u533a\u662f\u4ec0\u4e48\uff1f"
    query_shape, cardinality, _ = QueryShapeClassifier().classify(query)

    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=[
            {
                "entity_set": "A_CustomerSalesArea",
                "field_name": "CustomSalesAreaZone",
                "label": "\u9500\u552e\u7247\u533a",
                "description": "\u9500\u552e\u7247\u533a",
                "business_aliases": ["\u9500\u552e\u7247\u533a"],
            },
            {
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "Zone",
                "label": "\u7247\u533a",
                "description": "\u7247\u533a",
                "business_aliases": ["\u7247\u533a"],
            },
        ],
    )

    assert constraints.target_field_concepts == ["CustomSalesAreaZone"]
    assert "Zone" not in constraints.target_field_concepts
    assert constraints.filter_values == ["1000561"]


def test_required_target_field_survives_select_limit() -> None:
    fields = [{"field_name": f"DefaultField{i}"} for i in range(1, 10)]
    fields.append({"field_name": "AddressTimeZone"})
    selected = [field["field_name"] for field in fields[:-1]]

    result = RetrievalAwareIntentPlanner._apply_constraint_target_fields(
        selected,
        fields,
        constraints=type("Constraints", (), {"target_field_concepts": ["AddressTimeZone"]})(),
    )

    assert len(result) == 8
    assert "AddressTimeZone" in result
    assert "DefaultField9" not in result


def test_sales_district_query_plans_customer_sales_area_select(tmp_path: Path) -> None:
    _write_customer_sales_area_index(tmp_path)
    query = "\u5ba2\u62371000561\u7684\u9500\u552e\u5730\u533a\u662f\u4ec0\u4e48\uff1f"
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

    assert plan.entity_set == "A_CustomerSalesArea"
    assert "SalesDistrict" in plan.select_fields
    assert "Region" not in plan.select_fields
    assert [(item.field, item.operator, item.value) for item in plan.filters] == [("Customer", "eq", "1000561")]


def test_business_partner_sales_district_uses_dynamic_customer_bridge(tmp_path: Path) -> None:
    _write_customer_sales_area_index(tmp_path)
    query = "\u4e1a\u52a1\u4f19\u4f341000561\u7684\u9500\u552e\u5730\u533a\u662f\u4ec0\u4e48\uff1f"
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
    assert constraints.target_field_concepts == ["SalesDistrict"]
    assert plan.plan_kind == "multi_step"
    assert plan.target_field == "SalesDistrict"
    assert plan.entity_set == "A_CustomerSalesArea"
    assert plan.steps[0].entity_set == "A_BusinessPartner"
    assert [(item.field, item.operator, item.value) for item in plan.steps[0].filters] == [
        ("BusinessPartner", "eq", "1000561")
    ]
    assert plan.steps[1].entity_set == "A_CustomerSalesArea"
    assert plan.steps[1].filter_from_previous[0].field == "Customer"
    assert plan.steps[1].filter_from_previous[0].source_field == "Customer"
    assert "SalesDistrict" in plan.steps[1].select_fields


def test_business_partner_sales_organizations_use_customer_sales_area_bridge(tmp_path: Path) -> None:
    _write_customer_sales_area_index(tmp_path)
    query = "\u4e1a\u52a1\u4f19\u4f341000561\u5b58\u5728\u4e8e\u54ea\u4e9b\u9500\u552e\u7ec4\u7ec7\uff1f"
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

    assert query_shape == QueryShape.SEARCH_BY_ATTRIBUTE
    assert cardinality == CardinalityPolicy.MANY
    assert constraints.target_object == "business_partner"
    assert constraints.target_field_concepts == ["SalesOrganization"]
    assert plan.plan_kind == "multi_step"
    assert plan.target_field == "SalesOrganization"
    assert plan.steps[0].entity_set == "A_BusinessPartner"
    assert plan.steps[1].filter_from_previous[0].source_field in {"Customer", "BusinessPartner"}
    assert "SalesOrganization" in plan.steps[1].select_fields
