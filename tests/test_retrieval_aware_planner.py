import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, RetrievedContext, RetrievedDocument
from sap_odata_agent.infrastructure.llm.planner import RetrievalAwareIntentPlanner


def _write_index_fixture(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "description": "Business partner service",
                    "entity_sets": ["A_BusinessPartner", "A_CustomerSalesArea", "A_SupplierPurchasingOrg"],
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
                    "entity_set": "A_CustomerSalesArea",
                    "entity_type": "A_CustomerSalesAreaType",
                    "key_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division"],
                    "default_select_fields": ["Customer", "SalesOrganization", "DistributionChannel"],
                    "supported_methods": ["GET"],
                    "description": "Customer sales area data",
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
                    "field_name": "Customer",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Customer number",
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
                    "entity_set": "A_CustomerSalesArea",
                    "field_name": "Customer",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Customer number",
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
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "PaymentTerms",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Payment terms",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "ShippingCondition",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "Shipping condition",
                    "business_aliases": ["装运条件", "shipping condition"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "MaterialPlannedDeliveryDurn",
                    "data_type": "Edm.String",
                    "filterable": False,
                    "sortable": False,
                    "description": "Planned delivery time in days",
                    "business_aliases": ["计划交货时间", "planned delivery time", "delivery time"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "InvoiceIsGoodsReceiptBased",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                    "sortable": False,
                    "description": "Goods receipt based invoice verification flag",
                    "business_aliases": [
                        "基于收货的发票验证",
                        "基于收货的发票校验",
                        "goods receipt based invoice verification",
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text("[]", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_planner_prefers_root_entity_for_customer_profile_query(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_CustomerSalesArea",
                content="Likely entity candidate",
                score=43.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_CustomerSalesArea",
                    "key_fields": ["Customer", "SalesOrganization", "DistributionChannel", "Division"],
                    "default_select_fields": ["Customer", "SalesOrganization"],
                    "supported_methods": ["GET"],
                    "description": "Customer sales area data",
                },
            ),
            RetrievedDocument(
                source="entity-hint",
                title="A_BusinessPartner",
                content="Likely entity candidate",
                score=12.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName", "Customer"],
                    "supported_methods": ["GET", "PATCH"],
                    "description": "Business partner header data",
                },
            ),
            RetrievedDocument(
                source="field",
                title="A_BusinessPartner.Customer",
                content="Customer number field",
                score=4.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "Customer",
                    "description": "Customer number",
                },
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="查询客户1000001的基本信息"), context)

    assert plan.service_name == "API_TEST"
    assert plan.entity_set == "A_BusinessPartner"
    assert plan.http_method == "GET"
    assert plan.filters[0].field == "Customer"
    assert plan.filters[0].value == "1000001"
    assert "BusinessPartnerFullName" in plan.select_fields
    assert plan.planner_diagnostics["recall_strategy"] == "fallback_recall"
    assert plan.planner_diagnostics["field_candidates"]


def test_planner_marks_update_as_confirmation_required(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
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
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName", "Customer"],
                    "supported_methods": ["GET", "PATCH"],
                    "description": "Business partner header data",
                },
            )
        ]
    )

    plan = planner.plan(AgentRequest(user_input="修改客户1000001的名称"), context)

    assert plan.http_method == "PATCH"
    assert plan.requires_confirmation is True


def test_planner_prefers_supplier_purchasing_org_for_payment_terms_scope(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_BusinessPartner",
                content="Likely entity candidate",
                score=12.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName", "Customer"],
                    "supported_methods": ["GET", "PATCH"],
                    "description": "Business partner header data",
                },
            ),
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierPurchasingOrg",
                content="Supplier purchasing organization data",
                score=8.0,
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
                score=12.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "PaymentTerms",
                    "description": "Payment terms",
                },
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003在采购组织层级的付款条件是什么？"), context)

    assert plan.entity_set == "A_SupplierPurchasingOrg"
    assert plan.filters[0].field == "Supplier"
    assert "PaymentTerms" in plan.select_fields
    assert "PurchasingOrganization" in plan.select_fields


def test_planner_selects_planned_delivery_time_and_keeps_multiple_rows(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierPurchasingOrg",
                content="Supplier purchasing organization data",
                score=12.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "key_fields": ["Supplier", "PurchasingOrganization"],
                    "default_select_fields": ["Supplier", "PurchasingOrganization", "MaterialPlannedDeliveryDurn"],
                    "supported_methods": ["GET"],
                    "description": "Supplier purchasing organization data",
                },
            ),
            RetrievedDocument(
                source="field",
                title="A_SupplierPurchasingOrg.MaterialPlannedDeliveryDurn",
                content="planned delivery time field",
                score=16.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "MaterialPlannedDeliveryDurn",
                    "description": "Planned delivery time in days",
                },
            ),
        ]
    )

    plan = planner.plan(
        AgentRequest(user_input="供应商17300003在所有采购组织下的planned delivery time分别是多久？"),
        context,
    )

    assert plan.entity_set == "A_SupplierPurchasingOrg"
    assert plan.filters[0].field == "Supplier"
    assert "MaterialPlannedDeliveryDurn" in plan.select_fields
    assert "PurchasingOrganization" in plan.select_fields
    assert plan.top == 20


def test_planner_can_match_shipping_condition_with_typo_and_english_query(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierPurchasingOrg",
                content="Supplier purchasing organization data",
                score=8.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "key_fields": ["Supplier", "PurchasingOrganization"],
                    "default_select_fields": ["Supplier", "PurchasingOrganization", "ShippingCondition"],
                    "supported_methods": ["GET"],
                    "description": "Supplier purchasing organization data",
                },
            )
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003的shipping conditon是什么？"), context)

    assert plan.entity_set == "A_SupplierPurchasingOrg"
    assert plan.filters[0].field == "Supplier"
    assert "ShippingCondition" in plan.select_fields
    assert any(item["field_name"] == "ShippingCondition" for item in plan.planner_diagnostics["field_candidates"])


def test_planner_diagnostics_include_lookup_path_candidates(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="lookup-path-vector",
                title="supplier_to_postalcode_via_businesspartneraddress",
                content="Resolve Supplier to BusinessPartner, then read PostalCode from A_BusinessPartnerAddress.",
                score=18.0,
                metadata={
                    "path_id": "supplier_to_postalcode_via_businesspartneraddress",
                    "anchor_object": "Supplier",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "PostalCode",
                    "target_entity_set": "A_BusinessPartnerAddress",
                    "target_field": "PostalCode",
                    "description": "Resolve supplier to business partner address postal code.",
                    "steps": [
                        {"entity_set": "A_BusinessPartner", "filter_field": "Supplier"},
                        {"entity_set": "A_BusinessPartnerAddress", "filter_field": "BusinessPartner"},
                    ],
                },
            )
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商643266的邮编是多少？"), context)

    assert plan.planner_diagnostics["path_candidates"]
    assert plan.planner_diagnostics["path_candidates"][0]["target_field"] == "PostalCode"


def test_planner_prefers_specific_boolean_field_entity_over_root_entity(tmp_path: Path) -> None:
    _write_index_fixture(tmp_path)
    planner = RetrievalAwareIntentPlanner(index_root=tmp_path, service_name="API_TEST")
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="entity-hint",
                title="A_Supplier",
                content="Supplier header data",
                score=12.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "key_fields": ["Supplier"],
                    "default_select_fields": ["Supplier"],
                    "supported_methods": ["GET"],
                    "description": "Supplier header data",
                },
            ),
            RetrievedDocument(
                source="entity-hint",
                title="A_SupplierPurchasingOrg",
                content="Supplier purchasing organization data",
                score=10.0,
                metadata={
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPurchasingOrg",
                    "key_fields": ["Supplier", "PurchasingOrganization"],
                    "default_select_fields": ["Supplier", "PurchasingOrganization", "InvoiceIsGoodsReceiptBased"],
                    "supported_methods": ["GET"],
                    "description": "Supplier purchasing organization data",
                },
            ),
            RetrievedDocument(
                source="business-term",
                title="基于收货的发票校验->A_SupplierPurchasingOrg",
                content="Business term maps to invoice verification flag",
                score=16.0,
                metadata={
                    "mapped_entity_set": "A_SupplierPurchasingOrg",
                    "mapped_fields": ["InvoiceIsGoodsReceiptBased"],
                },
            ),
            RetrievedDocument(
                source="field-vector",
                title="A_SupplierPurchasingOrg.InvoiceIsGoodsReceiptBased",
                content="InvoiceIsGoodsReceiptBased field",
                score=14.0,
                metadata={
                    "entity_set": "A_SupplierPurchasingOrg",
                    "field_name": "InvoiceIsGoodsReceiptBased",
                },
            ),
        ]
    )

    plan = planner.plan(AgentRequest(user_input="供应商17300003是基于收货的发票校验吗？"), context)

    assert plan.entity_set == "A_SupplierPurchasingOrg"
    assert "InvoiceIsGoodsReceiptBased" in plan.select_fields
