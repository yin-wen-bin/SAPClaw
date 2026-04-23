import json
from pathlib import Path

from sap_odata_agent.application.context_gate import ContextCarryGate
from sap_odata_agent.domain.models import AgentRequest, CardinalityPolicy, QueryConstraints, QueryShape, RetrievedContext, RetrievedDocument
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor
from sap_odata_agent.infrastructure.llm.planner import RetrievalAwareIntentPlanner
from sap_odata_agent.infrastructure.llm.query_classifier import QueryShapeClassifier


def _write_index_fixture(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "description": "Test service",
                    "entity_sets": [
                        "A_BusinessPartner",
                        "A_BusinessPartnerAddress",
                        "A_SupplierPurchasingOrg",
                        "A_SupplierCompany",
                        "A_CustomerSalesArea",
                    ],
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
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName", "Supplier"],
                    "supported_methods": ["GET"],
                    "description": "Business partner header data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "entity_type": "A_BusinessPartnerAddressType",
                    "key_fields": ["BusinessPartner", "AddressID"],
                    "default_select_fields": ["BusinessPartner", "CityName", "PostalCode"],
                    "supported_methods": ["GET"],
                    "description": "Business partner address data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "entity_type": "A_SupplierPurchasingOrgType",
                    "key_fields": ["Supplier", "PurchasingOrganization"],
                    "default_select_fields": ["Supplier", "PurchasingOrganization", "PaymentTerms"],
                    "supported_methods": ["GET"],
                    "description": "Supplier purchasing organization data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "entity_type": "A_SupplierCompanyType",
                    "key_fields": ["Supplier", "CompanyCode"],
                    "default_select_fields": ["Supplier", "CompanyCode", "PaymentTerms", "ReconciliationAccount"],
                    "supported_methods": ["GET"],
                    "description": "Supplier company data",
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
                    "field_name": "Supplier",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Supplier number",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartnerFullName",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Business partner full name",
                    "business_aliases": ["名称", "name", "full name"],
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
                    "field_name": "CityName",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "City name",
                    "business_aliases": ["城市", "city"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "PostalCode",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Postal code",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "Region",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "label": "地区",
                    "description": "Region",
                    "business_aliases": ["地区", "region"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "Supplier",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Supplier number",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "PurchasingOrganization",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Purchasing organization",
                    "business_aliases": ["采购组织", "purchasing organization"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "PaymentTerms",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Payment terms",
                    "business_aliases": ["付款条件", "payment terms"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "field_name": "Supplier",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Supplier number",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "field_name": "CompanyCode",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "label": "公司代码",
                    "description": "Company code",
                    "business_aliases": ["公司代码", "company code"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "field_name": "PaymentTerms",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Payment terms",
                    "business_aliases": ["付款条件", "payment terms"],
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
                    "label": "销售组织",
                    "description": "Sales organization",
                    "business_aliases": ["销售组织", "sales organization"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "DistributionChannel",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "label": "分销渠道",
                    "description": "Distribution channel",
                    "business_aliases": ["分销渠道", "distribution channel"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "Division",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "label": "产品组",
                    "description": "Division",
                    "business_aliases": ["产品组", "division"],
                },
            ]
        ),
        encoding="utf-8",
    )
    for filename, payload in {
        "relations.json": "[]",
        "entity_graph.json": "[]",
        "business_terms.json": "[]",
    }.items():
        (service_dir / filename).write_text(payload, encoding="utf-8")
    (service_dir / "lookup_paths.json").write_text(
        json.dumps(
            [
                {
                    "path_id": "supplier_list_by_cityname_via_a_businesspartneraddress",
                    "service_name": "API_TEST",
                    "anchor_object": "Supplier",
                    "target_entity_set": "A_BusinessPartner",
                    "target_field": "CityName",
                    "path_kind": "attribute_filter_list",
                    "return_object": "Supplier",
                    "filter_fields": ["CityName"],
                    "result_fields": ["Supplier", "BusinessPartner", "BusinessPartnerFullName"],
                    "description": "Filter suppliers by city via business partner address.",
                    "business_aliases": ["城市", "city"],
                    "steps": [
                        {
                            "step_id": "filter_address",
                            "entity_set": "A_BusinessPartnerAddress",
                            "filter_field": "CityName",
                            "select_fields": ["BusinessPartner", "CityName", "PostalCode"],
                            "top": 50,
                        },
                        {
                            "step_id": "resolve_supplier",
                            "entity_set": "A_BusinessPartner",
                            "filter_field": "BusinessPartner",
                            "select_fields": ["BusinessPartner", "Supplier", "BusinessPartnerFullName"],
                            "top": 50,
                        },
                    ],
                    "confidence": 0.9,
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_query_shape_classifier_keeps_full_question_as_list_query() -> None:
    classifier = QueryShapeClassifier()

    shape, cardinality, _ = classifier.classify("帮我列出销售组织1710的所有客户", previous_clarification_question="请说明公司代码层级还是采购组织层级")

    assert shape == QueryShape.LIST_QUERY
    assert cardinality == CardinalityPolicy.MANY


def test_query_shape_classifier_recognizes_dimension_attribute_terms() -> None:
    classifier = QueryShapeClassifier()

    shape, cardinality, diagnostics = classifier.classify("采购组织1710的供应商")

    assert shape == QueryShape.SEARCH_BY_ATTRIBUTE
    assert cardinality == CardinalityPolicy.UNKNOWN
    assert diagnostics["matched_terms"] == ["attribute"]


def test_context_gate_rejects_full_standalone_question_even_with_clarification_context() -> None:
    gate = ContextCarryGate()

    decision = gate.decide(
        "帮我列出销售组织1710的所有客户",
        QueryShape.LIST_QUERY,
        {"final_status": "clarification_requested"},
    )

    assert decision.should_carry is False
    assert decision.reason == "standalone_question_detected"


def test_context_gate_accepts_short_follow_up_reply() -> None:
    gate = ContextCarryGate()

    decision = gate.decide(
        "没有时间限制",
        QueryShape.SINGLE_FACT,
        {"final_status": "clarification_requested"},
    )

    assert decision.should_carry is True
    assert decision.reason == "short_contextual_reply_detected"


def test_constraint_extractor_keeps_attribute_filters_separate_from_answer_fields() -> None:
    extractor = QueryConstraintExtractor()
    constraints = extractor.extract(
        "城市为San Diego的供应商有哪些？",
        QueryShape.SEARCH_BY_ATTRIBUTE,
        CardinalityPolicy.MANY,
        candidate_fields=[
            {
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "CityName",
                "label": "城市",
                "description": "城市",
            }
        ],
    )

    assert constraints.target_object == "supplier"
    assert constraints.filter_concepts == ["CityName"]
    assert "San Diego" in constraints.filter_values
    assert constraints.target_field_concepts == []


def test_constraint_extractor_treats_region_as_target_field_not_filter() -> None:
    extractor = QueryConstraintExtractor()
    constraints = extractor.extract(
        "\u4e1a\u52a1\u4f19\u4f341000561\u7684\u5730\u533a\u662f\u54ea\u91cc\uff1f",
        QueryShape.SINGLE_FACT,
        CardinalityPolicy.ONE,
        candidate_fields=[
            {
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "Region",
                "label": "\u5730\u533a",
                "description": "\u5730\u533a\uff08\u7701/\u81ea\u6cbb\u533a/\u76f4\u8f96\u5e02\uff09",
                "business_aliases": ["\u5730\u533a"],
            }
        ],
    )

    assert constraints.target_object == "business_partner"
    assert constraints.target_field_concepts == ["Region"]
    assert constraints.filter_concepts == []
    assert "1000561" in constraints.filter_values


def test_attribute_filter_query_extracts_region_filter_and_supplier_list_intent() -> None:
    query = "\u67e5\u627e\u5730\u533a\u4e3aHH\u7684\u4f9b\u5e94\u5546"

    query_shape, cardinality, diagnostics = QueryShapeClassifier().classify(query)
    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=[
            {
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "Region",
                "label": "地区",
                "description": "地区",
            }
        ],
    )

    assert query_shape == QueryShape.SEARCH_BY_ATTRIBUTE
    assert cardinality == CardinalityPolicy.MANY
    assert diagnostics["matched_terms"] == ["attribute"]
    assert constraints.target_object == "supplier"
    assert constraints.filter_concepts == ["Region"]
    assert constraints.filter_values == ["HH"]
    assert constraints.target_field_concepts == []


def test_attribute_filter_query_preserves_email_value() -> None:
    query = "查询email为info@10300006.com的BP"

    query_shape, cardinality, diagnostics = QueryShapeClassifier().classify(query)
    constraints = QueryConstraintExtractor().extract(
        query,
        query_shape,
        cardinality,
        candidate_fields=[
            {
                "entity_set": "A_AddressEmailAddress",
                "field_name": "EmailAddress",
                "label": "电子邮件地址",
                "description": "email address",
                "business_aliases": ["email"],
            }
        ],
    )

    assert query_shape == QueryShape.SEARCH_BY_ATTRIBUTE
    assert diagnostics["matched_terms"] == ["attribute"]
    assert constraints.target_object == "business_partner"
    assert constraints.filter_concepts == ["EmailAddress"]
    assert constraints.filter_values == ["info@10300006.com"]


def test_constraint_extractor_uses_dynamic_candidate_fields_for_sales_organization() -> None:
    extractor = QueryConstraintExtractor()
    constraints = extractor.extract(
        "帮我列出销售组织1710的所有客户",
        QueryShape.LIST_QUERY,
        CardinalityPolicy.MANY,
        candidate_fields=[
            {
                "entity_set": "A_CustomerSalesArea",
                "field_name": "SalesOrganization",
                "label": "销售组织",
                "description": "Sales organization",
                "business_aliases": ["销售组织", "sales organization"],
                "filterable": True,
            }
        ],
    )

    assert constraints.target_object == "customer"
    assert constraints.filter_concepts == ["SalesOrganization"]
    assert "1710" in constraints.filter_values


def test_constraint_extractor_recognizes_company_code_and_purchasing_org() -> None:
    extractor = QueryConstraintExtractor()

    company_constraints = extractor.extract(
        "列出公司代码1710下的所有供应商",
        QueryShape.LIST_QUERY,
        CardinalityPolicy.MANY,
        candidate_fields=[
            {
                "entity_set": "A_SupplierCompany",
                "field_name": "CompanyCode",
                "label": "公司代码",
                "description": "公司代码",
            }
        ],
    )
    purchasing_constraints = extractor.extract(
        "采购组织1710的供应商都有哪些？",
        QueryShape.LIST_QUERY,
        CardinalityPolicy.MANY,
        candidate_fields=[
            {
                "entity_set": "A_SupplierPurchasingOrg",
                "field_name": "PurchasingOrganization",
                "label": "采购组织",
                "description": "采购组织",
            }
        ],
    )

    assert company_constraints.target_object == "supplier"
    assert company_constraints.filter_concepts == ["CompanyCode"]
    assert "1710" in company_constraints.filter_values
    assert purchasing_constraints.target_object == "supplier"
    assert purchasing_constraints.filter_concepts == ["PurchasingOrganization"]
    assert "1710" in purchasing_constraints.filter_values


def test_planner_uses_many_cardinality_for_list_queries(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierPurchasingOrg",
                content="Supplier purchasing organization data",
                score=18.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "key_fields": ["Supplier", "PurchasingOrganization"],
                    "default_select_fields": ["Supplier", "PurchasingOrganization", "PaymentTerms"],
                    "supported_methods": ["GET"],
                    "description": "Supplier purchasing organization data",
                },
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierPurchasingOrg.PaymentTerms",
                content="Payment terms field",
                score=16.0,
                metadata={"entity_set": "A_SupplierPurchasingOrg", "field_name": "PaymentTerms"},
            ),
        ]
    )

    request = AgentRequest(
        user_input="采购组织1710下，付款条件为0001的供应商都有哪些？",
        query_shape=QueryShape.LIST_QUERY,
        cardinality_policy=CardinalityPolicy.MANY,
        constraints=QueryConstraints(
            query_shape=QueryShape.LIST_QUERY,
            cardinality=CardinalityPolicy.MANY,
            target_object="supplier",
            target_field_concepts=[],
            filter_concepts=["PaymentTerms"],
            filter_values=["1710", "0001"],
        ),
    )
    plan = planner.plan(request, context)

    assert plan.entity_set == "A_SupplierPurchasingOrg"
    assert plan.top == 50


def test_planner_uses_contains_for_name_search_constraints(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_BusinessPartner",
                content="Business partner header data",
                score=20.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                    "supported_methods": ["GET"],
                    "description": "Business partner header data",
                },
            ),
            RetrievedDocument(
                source="field",
                title="A_BusinessPartner.BusinessPartnerFullName",
                content="Business partner full name",
                score=18.0,
                metadata={"entity_set": "A_BusinessPartner", "field_name": "BusinessPartnerFullName"},
            ),
        ]
    )

    request = AgentRequest(
        user_input="名称中包含“Inlandskunde”的BP都有哪些？",
        query_shape=QueryShape.NAME_CONTAINS_SEARCH,
        cardinality_policy=CardinalityPolicy.MANY,
        constraints=QueryConstraints(
            query_shape=QueryShape.NAME_CONTAINS_SEARCH,
            cardinality=CardinalityPolicy.MANY,
            target_object="business_partner",
            target_field_concepts=["BusinessPartnerFullName"],
            filter_concepts=["BusinessPartnerFullName"],
            filter_values=["Inlandskunde"],
            name_match_mode="contains",
        ),
    )

    plan = planner.plan(request, context)

    assert plan.entity_set == "A_BusinessPartner"
    assert plan.filters
    assert plan.filters[0].field == "BusinessPartnerFullName"
    assert plan.filters[0].operator == "contains"
    assert plan.top == 50


def test_planner_prefers_attribute_filter_path_for_supplier_list_by_city(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="lookup-path",
                title="supplier_list_by_cityname_via_a_businesspartneraddress",
                content="Filter suppliers by city via business partner address.",
                score=22.0,
                metadata={
                    "path_id": "supplier_list_by_cityname_via_a_businesspartneraddress",
                    "anchor_object": "Supplier",
                    "target_entity_set": "A_BusinessPartner",
                    "target_field": "CityName",
                    "path_kind": "attribute_filter_list",
                    "return_object": "Supplier",
                    "filter_fields": ["CityName"],
                    "result_fields": ["Supplier", "BusinessPartner", "BusinessPartnerFullName"],
                    "steps": [
                        {
                            "step_id": "filter_address",
                            "entity_set": "A_BusinessPartnerAddress",
                            "filter_field": "CityName",
                            "select_fields": ["BusinessPartner", "CityName", "PostalCode"],
                            "top": 50,
                        },
                        {
                            "step_id": "resolve_supplier",
                            "entity_set": "A_BusinessPartner",
                            "filter_field": "BusinessPartner",
                            "select_fields": ["BusinessPartner", "Supplier", "BusinessPartnerFullName"],
                            "top": 50,
                        },
                    ],
                    "business_aliases": ["城市", "city"],
                },
            ),
            RetrievedDocument(
                source="entity-hint",
                title="A_CustSalesPartnerFunc",
                content="Unrelated partner function entity",
                score=10.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_CustSalesPartnerFunc",
                    "key_fields": ["Customer"],
                    "default_select_fields": ["Customer"],
                    "supported_methods": ["GET"],
                    "description": "Customer sales partner function data",
                },
            ),
        ]
    )
    request = AgentRequest(
        user_input="城市为San Diego的供应商有哪些？",
        query_shape=QueryShape.SEARCH_BY_ATTRIBUTE,
        cardinality_policy=CardinalityPolicy.MANY,
        constraints=QueryConstraintExtractor().extract(
            "城市为San Diego的供应商有哪些？",
            QueryShape.SEARCH_BY_ATTRIBUTE,
            CardinalityPolicy.MANY,
        ),
    )

    plan = planner.plan(request, context)

    assert plan.plan_kind == "multi_step"
    assert plan.path_id == "supplier_list_by_cityname_via_a_businesspartneraddress"
    assert plan.steps[0].filters[0].field == "CityName"
    assert plan.steps[0].filters[0].value == "San Diego"


def test_planner_synthesizes_attribute_filter_path_for_supplier_list_by_region(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    query = "\u67e5\u627e\u5730\u533a\u4e3aHH\u7684\u4f9b\u5e94\u5546"
    query_shape, cardinality, _ = QueryShapeClassifier().classify(query)
    request = AgentRequest(
        user_input=query,
        query_shape=query_shape,
        cardinality_policy=cardinality,
        constraints=QueryConstraintExtractor().extract(
            query,
            query_shape,
            cardinality,
            candidate_fields=[
                {
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "Region",
                    "label": "地区",
                    "description": "地区",
                }
            ],
        ),
    )

    plan = planner.plan(request, RetrievedContext())

    assert plan.plan_kind == "multi_step"
    assert plan.path_id == "supplier_list_by_region_via_a_businesspartneraddress_dynamic"
    assert plan.steps[0].entity_set == "A_BusinessPartnerAddress"
    assert plan.steps[0].filters[0].field == "Region"
    assert plan.steps[0].filters[0].value == "HH"
    assert plan.steps[-1].entity_set == "A_BusinessPartner"
    assert "Supplier" in plan.steps[-1].select_fields


def test_planner_document_bias_ignores_empty_business_term_mapped_fields() -> None:
    scores = RetrievalAwareIntentPlanner._build_document_bias(
        [
            RetrievedDocument(
                source="business-term",
                title="empty mapped fields",
                content="Business term with entity only",
                score=12.0,
                metadata={
                    "mapped_entity_set": "A_BusinessPartner",
                    "mapped_fields": [],
                },
            )
        ]
    )

    assert scores["A_BusinessPartner"] == 12.0
    assert all("." not in key for key in scores)


def test_planner_prefers_direct_customer_sales_area_for_sales_org_list(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_CustomerSalesArea",
                content="Customer sales area data",
                score=24.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "key_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division"],
                    "default_select_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division"],
                    "supported_methods": ["GET"],
                    "description": "Customer sales area data",
                },
            ),
            RetrievedDocument(
                source="field-vector",
                title="A_CustomerSalesArea.SalesOrganization",
                content="Sales organization field",
                score=20.0,
                metadata={
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "SalesOrganization",
                },
            ),
        ]
    )

    request = AgentRequest(
        user_input="帮我列出销售组织1710的所有客户",
        query_shape=QueryShape.LIST_QUERY,
        cardinality_policy=CardinalityPolicy.MANY,
        constraints=QueryConstraintExtractor().extract(
            "帮我列出销售组织1710的所有客户",
            QueryShape.LIST_QUERY,
            CardinalityPolicy.MANY,
            candidate_fields=[
                {
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "SalesOrganization",
                    "label": "销售组织",
                    "description": "Sales organization",
                    "business_aliases": ["销售组织", "sales organization"],
                    "filterable": True,
                }
            ],
        ),
    )

    plan = planner.plan(request, context)

    assert plan.plan_kind == "direct"
    assert plan.entity_set == "A_CustomerSalesArea"
    assert plan.filters[0].field == "SalesOrganization"
    assert plan.filters[0].value == "1710"
    assert plan.top == 50


def test_planner_prefers_direct_supplier_company_for_company_code_list(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierCompany",
                content="Supplier company data",
                score=24.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierCompany",
                    "key_fields": ["Supplier", "CompanyCode"],
                    "default_select_fields": ["Supplier", "CompanyCode", "PaymentTerms", "ReconciliationAccount"],
                    "supported_methods": ["GET"],
                    "description": "Supplier company data",
                },
            ),
            RetrievedDocument(
                source="field-vector",
                title="A_SupplierCompany.CompanyCode",
                content="Company code field",
                score=20.0,
                metadata={
                    "entity_set": "A_SupplierCompany",
                    "field_name": "CompanyCode",
                },
            ),
        ]
    )

    request = AgentRequest(
        user_input="列出公司代码1710下的所有供应商",
        query_shape=QueryShape.LIST_QUERY,
        cardinality_policy=CardinalityPolicy.MANY,
            constraints=QueryConstraintExtractor().extract(
                "列出公司代码1710下的所有供应商",
                QueryShape.LIST_QUERY,
                CardinalityPolicy.MANY,
                candidate_fields=[
                    {
                        "entity_set": "A_SupplierCompany",
                        "field_name": "CompanyCode",
                        "label": "公司代码",
                        "description": "公司代码",
                    }
                ],
            ),
    )

    plan = planner.plan(request, context)

    assert plan.plan_kind == "direct"
    assert plan.entity_set == "A_SupplierCompany"
    assert plan.filters[0].field == "CompanyCode"
    assert plan.filters[0].value == "1710"
    assert plan.top == 50


def test_planner_keeps_region_in_select_fields_for_business_partner_question(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_BusinessPartnerAddress",
                content="Business partner address data",
                score=24.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "key_fields": ["BusinessPartner", "AddressID"],
                    "default_select_fields": ["BusinessPartner", "CityName", "PostalCode"],
                    "supported_methods": ["GET"],
                    "description": "Business partner address data",
                },
            ),
            RetrievedDocument(
                source="field-vector",
                title="A_BusinessPartnerAddress.Region",
                content="Region field",
                score=18.0,
                metadata={
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "Region",
                },
            ),
        ]
    )

    request = AgentRequest(
        user_input="业务伙伴1000561的地区是哪里？",
        query_shape=QueryShape.SINGLE_FACT,
        cardinality_policy=CardinalityPolicy.ONE,
        constraints=QueryConstraintExtractor().extract(
            "业务伙伴1000561的地区是哪里？",
            QueryShape.SINGLE_FACT,
            CardinalityPolicy.ONE,
        ),
    )

    plan = planner.plan(request, context)

    assert plan.entity_set == "A_BusinessPartnerAddress"
    assert any(item.field == "BusinessPartner" and item.value == "1000561" for item in plan.filters)
    assert "Region" in plan.select_fields
