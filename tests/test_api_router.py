from __future__ import annotations

import json

from sap_odata_agent.api.routes.agent import _history_entry_to_payload
from sap_odata_agent.infrastructure.llm.api_router import LlmApiRouter


class SequencedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _catalog() -> list[dict]:
    return [
        {
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "short_description": "Purchase order processing API.",
            "primary_business_objects": ["Purchase Order", "Purchase Order Item"],
            "top_entities": ["A_PurchaseOrder", "A_PurchaseOrderItem"],
            "top_filter_fields": ["A_PurchaseOrderItem.IsFinallyInvoiced"],
            "top_answer_fields": ["A_PurchaseOrder.PurchaseOrder"],
            "api_skill_summary": (
                "Use this API for purchase order transaction questions. "
                "The user asks for 采购订单 by 供应商, 物料, 工厂, 公司代码, 交货日期, 未收货, or 未清发票. "
                "The user asks for purchase orders by supplier, material, plant, company code, "
                "creation date, delivery date, item status, invoice status, or goods receipt status."
            ),
        }
    ]


def _product_catalog() -> list[dict]:
    return [
        {
            "service_name": "API_PRODUCT_SRV",
            "short_description": "Product/material master data API.",
            "primary_business_objects": ["Product", "Material"],
            "top_entities": ["A_Product", "A_ProductDescription"],
            "top_filter_fields": ["A_Product.Product"],
            "top_answer_fields": ["A_Product.Product", "A_Product.BaseUnit", "A_Product.ProductGroup"],
            "api_skill_summary": (
                "Use this API for product or material master data. "
                "For product master data by material/product ID, select Product, ProductType, "
                "ProductGroup, BaseUnit, 物料组, and 基本单位 when available.\n"
                "Do not use this API for purchase orders."
            ),
        }
    ]


def _ap_catalog() -> list[dict]:
    return [
        {
            "service_name": "API_GLACCOUNTLINEITEM",
            "short_description": "G/L Account Line Items - Read (A2X).",
            "primary_business_objects": ["G/L Account Line Item", "Supplier AP Open Item", "Supplier AP Balance"],
            "top_entities": ["GLAccountLineItem"],
            "top_filter_fields": ["GLAccountLineItem.Supplier", "GLAccountLineItem.ClearingDate"],
            "top_answer_fields": [
                "GLAccountLineItem.AccountingDocument",
                "GLAccountLineItem.Supplier",
                "GLAccountLineItem.AmountInCompanyCodeCurrency",
            ],
            "api_skill_summary": (
                "For supplier open payable wording such as 供应商...是否有未清的应付款, "
                "供应商未清应付款, or 供应商未付款, use GLAccountLineItem directly. "
                "For supplier AP balance wording such as 供应商...应付款总额 or 供应商应付账款余额, "
                "use GLAccountLineItem with result_transform aggregate. "
                "For supplier open payable wording, use GLAccountLineItem directly. "
                "Filter Supplier when provided and ClearingDate eq null for open items."
            ),
        },
        {
            "service_name": "API_OPLACCTGDOCITEMCUBE_SRV",
            "short_description": "Operational accounting document item cube.",
            "primary_business_objects": ["Operational Accounting Item"],
            "top_entities": ["A_OperationalAcctgDocItemCube"],
            "top_filter_fields": ["A_OperationalAcctgDocItemCube.Supplier", "A_OperationalAcctgDocItemCube.ClearingDate"],
            "top_answer_fields": ["A_OperationalAcctgDocItemCube.AccountingDocument"],
        },
    ]


def test_api_router_skill_fallback_product_master_attribute_query_without_llm() -> None:
    router = LlmApiRouter(llm_client=None, enabled=False, allow_default_fallback=False)

    decision = router.route("查询物料TG0011的base unit和物料组", _product_catalog())

    assert decision.selected_apis[0].service_name == "API_PRODUCT_SRV"
    assert decision.raw_response["router_fallback"] == "skill_catalog_similarity"
    assert decision.needs_clarification is False


def test_api_router_skill_fallback_prefers_purchase_order_over_product_for_transaction_query() -> None:
    router = LlmApiRouter(llm_client=None, enabled=False, allow_default_fallback=False)

    decision = router.route("查询物料TG0011的采购订单", [*_product_catalog(), *_catalog()])

    assert decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"
    assert decision.raw_response["router_fallback"] == "skill_catalog_similarity"


def test_api_router_skill_fallback_supplier_purchase_order_query_without_llm() -> None:
    router = LlmApiRouter(llm_client=None, enabled=False, allow_default_fallback=False)

    decision = router.route("查询供应商1730003的采购订单", _catalog())

    assert decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"
    assert decision.raw_response["router_fallback"] == "skill_catalog_similarity"
    assert decision.needs_clarification is False


def test_api_router_excludes_cds_view_only_api_from_prompt_and_selection() -> None:
    client = SequencedClient(
        [
            json.dumps(
                {
                    "resolved_user_input": "show purchase orders arriving last week",
                    "should_carry_context": False,
                    "selected_apis": [
                        {
                            "service_name": "I_PurchaseOrderHistoryAPI01",
                            "confidence": 0.9,
                            "reason": "Purchase order history has goods receipt fields.",
                        }
                    ],
                    "requires_multi_api": False,
                    "intent_summary": "Purchase orders arriving last week.",
                    "business_domain": "Procurement",
                    "business_object": "Purchase Order",
                    "needs_clarification": False,
                    "clarification_question": "",
                    "clarification_options": [],
                }
            )
        ]
    )
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)
    catalog = [
        {
            "service_name": "I_PurchaseOrderHistoryAPI01",
            "service_kind": "CDS_VIEW_ONLY",
            "runtime_available": False,
            "odata_runtime_available": False,
            "short_description": "Purchase Order History with goods receipt and delivery document fields.",
            "primary_business_objects": ["Purchase Order History"],
            "top_entities": ["I_PurchaseOrderHistoryAPI01"],
            "top_filter_fields": ["I_PurchaseOrderHistoryAPI01.PostingDate"],
            "top_answer_fields": ["I_PurchaseOrderHistoryAPI01.PurchaseOrder"],
        },
        {
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "service_kind": "ODATA",
            "runtime_available": True,
            "odata_runtime_available": True,
            "short_description": "Purchase order processing API.",
            "primary_business_objects": ["Purchase Order", "Purchase Order Schedule Line"],
            "top_entities": ["A_PurchaseOrder", "A_PurchaseOrderScheduleLine"],
            "top_filter_fields": ["A_PurchaseOrderScheduleLine.ScheduleLineDeliveryDate"],
            "top_answer_fields": ["A_PurchaseOrderScheduleLine.PurchaseOrder"],
            "api_skill_summary": (
                "Use this API for purchase order transaction questions by delivery date, arriving date, "
                "or schedule-line delivery date. Use A_PurchaseOrderScheduleLine.ScheduleLineDeliveryDate."
            ),
        },
    ]

    decision = router.route("show purchase orders arriving last week", catalog)

    assert "I_PurchaseOrderHistoryAPI01" not in client.calls[0]["user_prompt"]
    assert decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"
    assert decision.raw_response["router_fallback"] == "skill_catalog_similarity"

    fallback_router = LlmApiRouter(llm_client=None, enabled=False, allow_default_fallback=False)
    fallback_decision = fallback_router.route("查询上周到货的采购订单", catalog)

    assert fallback_decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"
    assert fallback_decision.raw_response["router_fallback"] == "skill_catalog_similarity"


def test_api_router_skill_fallback_supplier_open_payables_query_without_llm() -> None:
    router = LlmApiRouter(llm_client=None, enabled=False, allow_default_fallback=False)

    decision = router.route("供应商USSU-VSF08是否有未清的应付款？", _ap_catalog())

    assert decision.selected_apis[0].service_name == "API_GLACCOUNTLINEITEM"
    assert decision.raw_response["router_fallback"] == "skill_catalog_similarity"
    assert decision.needs_clarification is False


def test_api_router_repairs_supplier_payable_total_to_gl_line_items() -> None:
    client = SequencedClient(
        [
            {
                "resolved_user_input": "查询供应商17300003在公司代码1710下，截止目前的应付款总额。",
                "should_carry_context": False,
                "selected_apis": [
                    {
                        "service_name": "API_OPLACCTGDOCITEMCUBE_SRV",
                        "confidence": 0.77,
                        "reason": "Initial AP amount match.",
                    }
                ],
                "requires_multi_api": False,
                "intent_summary": "Supplier payable total by company code as of today.",
                "business_domain": "Finance",
                "business_object": "Supplier payable balance",
                "needs_clarification": False,
                "clarification_question": "",
                "clarification_options": [],
            }
        ]
    )
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询供应商17300003在公司代码1710下，截止目前的应付款总额。", _ap_catalog())

    assert decision.selected_apis[0].service_name == "API_GLACCOUNTLINEITEM"
    assert decision.needs_clarification is False


def test_router_catalog_compaction_keeps_specific_matching_entities() -> None:
    entry = {
        "service_name": "API_SALES_ORDER_SRV",
        "short_description": "Sales order API.",
        "primary_business_objects": [
            "Sales Order",
            "Sales Order Item",
            "Sales Order Itm Subsqnt Proc Flow",
            "Sales Order Subsqnt Proc Flow",
            "Sales Order Header Pr Element",
            "Sales Order Item Pr Element",
            "Sales Order Header Partner",
            "Sales Order Partner Address",
            "Sales Order Related Object",
            "Sales Order Billing Plan Item",
        ],
        "top_entities": [
            "A_SalesOrder",
            "A_SalesOrderItem",
            "A_SalesOrderItmSubsqntProcFlow",
            "A_SalesOrderSubsqntProcFlow",
            "A_SalesOrderHeaderPrElement",
            "A_SalesOrderItemPrElement",
            "A_SalesOrderHeaderPartner",
            "A_SalesOrderPartnerAddress",
            "A_SalesOrderRelatedObject",
            "A_SalesOrderBillingPlanItem",
        ],
        "top_filter_fields": [
            "A_SalesOrder.SalesOrder",
            "A_SalesOrderItem.Material",
            "A_SalesOrderItem.DeliveryStatus",
            "A_SalesOrder.OverallTotalDeliveryStatus",
            "A_SalesOrderBillingPlanItem.SalesOrder",
        ],
        "top_answer_fields": [
            "A_SalesOrder.SalesOrder",
            "A_SalesOrderItem.SalesOrder",
            "A_SalesOrderItem.SalesOrderItem",
            "A_SalesOrderBillingPlanItem.BillingPlan",
            "A_SalesOrderBillingPlanItem.BillingPlanItem",
        ],
    }

    compact = LlmApiRouter._compact_catalog_for_prompt([entry], "List billing plan items for sales orders")[0]

    assert "Sales Order Billing Plan Item" in compact["primary_business_objects"]
    assert "A_SalesOrderBillingPlanItem" in compact["top_entities"]
    assert "A_SalesOrderBillingPlanItem.SalesOrder" in compact["top_filter_fields"]
    assert "A_SalesOrderBillingPlanItem.BillingPlan" in compact["top_answer_fields"]


def test_api_router_skill_fallback_after_router_timeout() -> None:
    client = SequencedClient([TimeoutError("timed out"), TimeoutError("timed out"), TimeoutError("timed out")])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("供应商USSU-VSF08是否有未清的应付款？", _ap_catalog())

    assert len(client.calls) == 3
    assert decision.selected_apis[0].service_name == "API_GLACCOUNTLINEITEM"
    assert decision.raw_response["router_fallback"] == "skill_catalog_similarity"
    assert decision.raw_response["fallback_reason"] == "api_router_failed:timed out"


def test_api_router_repairs_malformed_json_without_business_fallback() -> None:
    repaired = {
        "resolved_user_input": "query open invoice purchase orders",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.91,
                "reason": "Feedback memory and top_filter_fields match IsFinallyInvoiced.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Open invoice purchase orders",
        "business_domain": "Purchasing",
        "business_object": "Purchase Order",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    client = SequencedClient(
        [
            '{"resolved_user_input": "query open invoice purchase orders", selected_apis: [',
            json.dumps(repaired),
        ]
    )
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route(
        "query open invoice purchase orders",
        _catalog(),
        feedback_memories=[{"preferred_fields": ["IsFinallyInvoiced"]}],
    )

    assert len(client.calls) == 2
    assert "Repair only the JSON syntax" in client.calls[1]["user_prompt"]
    assert decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"
    assert decision.raw_response["selected_apis"][0]["confidence"] == 0.91


def test_api_router_regenerates_when_json_repair_is_still_invalid() -> None:
    valid = {
        "resolved_user_input": "query customer billing documents",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_BILLING_DOCUMENT_SRV",
                "confidence": 0.89,
                "reason": "Billing document wording matched the billing document API.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Customer billing documents",
        "business_domain": "Sales and Distribution",
        "business_object": "Billing Document",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_BILLING_DOCUMENT_SRV",
            "short_description": "Billing document API.",
            "primary_business_objects": ["Billing Document"],
            "top_entities": ["A_BillingDocument"],
            "top_filter_fields": ["A_BillingDocument.SoldToParty"],
            "top_answer_fields": ["A_BillingDocument.BillingDocument"],
        }
    ]
    client = SequencedClient(
        [
            '{"resolved_user_input": "query customer billing documents", "selected_apis": [',
            '{"resolved_user_input": "query customer billing documents", "selected_apis": [',
            json.dumps(valid),
        ]
    )
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("query customer billing documents", catalog)

    assert len(client.calls) == 3
    assert "Repair only the JSON syntax" in client.calls[1]["user_prompt"]
    assert "Regenerate the API routing decision" in client.calls[2]["user_prompt"]
    assert decision.selected_apis[0].service_name == "API_BILLING_DOCUMENT_SRV"


def test_api_router_retries_transport_failure_without_business_fallback() -> None:
    valid = {
        "resolved_user_input": "query purchase orders",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.8,
                "reason": "Purchase order business object matched.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Purchase orders",
        "business_domain": "Purchasing",
        "business_object": "Purchase Order",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    client = SequencedClient([TimeoutError("timed out"), json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("query purchase orders", _catalog())

    assert len(client.calls) == 2
    assert decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"


def test_api_router_repairs_purchase_order_supplier_contact_route() -> None:
    catalog = [
        {
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "short_description": "Purchase order processing API.",
            "primary_business_objects": ["Purchase Order"],
            "top_entities": ["A_PurchaseOrder", "A_PurchaseOrderItem", "A_PurchaseOrderScheduleLine"],
        },
        {
            "service_name": "API_BUSINESS_PARTNER",
            "short_description": "Business partner master data API.",
            "primary_business_objects": ["Supplier", "Business Partner"],
            "top_entities": ["A_Supplier", "A_BusinessPartnerAddress"],
        },
    ]
    valid = {
        "resolved_user_input": "\u67e5\u8be2\u5de5\u53821710\u660e\u5929\u5230\u8d27\u7684\u91c7\u8d2d\u8ba2\u5355\u7684\u4f9b\u5e94\u5546\u8054\u7cfb\u4eba\u4fe1\u606f",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.8,
                "reason": "Purchase order delivery date query.",
            }
        ],
        "requires_multi_api": True,
        "intent_summary": "Purchase order supplier contact lookup.",
        "business_domain": "Purchasing",
        "business_object": "Purchase Order",
        "needs_clarification": True,
        "clarification_question": "Need contact scope?",
        "clarification_options": [],
    }
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route(valid["resolved_user_input"], catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_PURCHASEORDER_PROCESS_SRV",
        "API_BUSINESS_PARTNER",
    ]
    assert decision.requires_multi_api is True
    assert decision.needs_clarification is False


def test_api_router_prompt_includes_api_skill_summary() -> None:
    valid = {
        "resolved_user_input": "query unreceived purchase orders",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.93,
                "reason": "The API skill says unreceived purchase orders use the PO item completion flag.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Unreceived purchase orders",
        "business_domain": "Purchasing",
        "business_object": "Purchase Order",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = _catalog()
    catalog[0]["api_skill_summary"] = (
        "For unreceived purchase orders, prefer A_PurchaseOrderItem.IsCompletelyDelivered eq false."
    )
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询未收货采购订单", catalog)

    assert decision.selected_apis[0].service_name == "API_PURCHASEORDER_PROCESS_SRV"
    assert "api_skill_summary" in client.calls[0]["user_prompt"]
    assert "IsCompletelyDelivered" in client.calls[0]["user_prompt"]
    assert "api_skill_summary" in client.calls[0]["system_prompt"]


def test_api_router_compacts_large_catalog_payload() -> None:
    valid = {
        "resolved_user_input": "query purchase orders",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.8,
                "reason": "Purchase order business object matched.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Purchase orders",
        "business_domain": "Purchasing",
        "business_object": "Purchase Order",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = _catalog()
    catalog[0]["short_description"] = "x" * 1000
    catalog[0]["primary_business_objects"] = [f"object-{index}" for index in range(12)]
    catalog[0]["top_entities"] = [f"Entity{index}" for index in range(12)]
    catalog[0]["top_filter_fields"] = [f"Entity.Field{index}" for index in range(12)]
    catalog[0]["top_answer_fields"] = [f"Entity.Answer{index}" for index in range(12)]
    catalog[0]["api_skill_summary"] = "For unreceived purchase orders, prefer A_PurchaseOrderItem.IsCompletelyDelivered eq false. " + "x" * 1000
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    router.route("query purchase orders", catalog)

    prompt = client.calls[0]["user_prompt"]
    payload = json.loads(prompt.split("Input:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
    compact_entry = payload["api_catalog"][0]
    assert len(compact_entry["short_description"]) <= 110
    assert len(compact_entry["primary_business_objects"]) == 4
    assert len(compact_entry["top_entities"]) == 4
    assert len(compact_entry["top_filter_fields"]) == 4
    assert len(compact_entry["top_answer_fields"]) == 4
    assert len(compact_entry["api_skill_summary"]) <= 700


def test_api_router_keeps_user_relevant_skill_guidance_after_compaction() -> None:
    valid = {
        "resolved_user_input": "query company 1710 chart of accounts",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_COMPANYCODE_SRV",
                "confidence": 0.91,
                "reason": "Company code API exposes ChartOfAccounts as an answer field.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Company code chart of accounts",
        "business_domain": "Finance",
        "business_object": "Company Code",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_COMPANYCODE_SRV",
            "short_description": "Company code master data.",
            "primary_business_objects": ["Company Code"],
            "top_entities": ["A_CompanyCode"],
            "top_filter_fields": ["A_CompanyCode.CompanyCode", "A_CompanyCode.ChartOfAccounts"],
            "top_answer_fields": ["A_CompanyCode.ChartOfAccounts"],
            "api_skill_summary": (
                "Generic company code guidance. " + ("x" * 300) + "\n"
                "- For company code chart of accounts requests, query "
                "A_CompanyCode.ChartOfAccounts directly."
            ),
        }
    ]
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("query company 1710 chart of accounts", catalog)

    assert decision.selected_apis[0].service_name == "API_COMPANYCODE_SRV"
    prompt = client.calls[0]["user_prompt"]
    assert "Relevant skill guidance" in prompt
    assert "A_CompanyCode.ChartOfAccounts directly" in prompt


def test_api_router_prioritizes_exact_skill_guidance_over_generic_line_item_matches() -> None:
    skill_summary = (
        "For balance drilldown wording, use companion API C_TRIALBALANCE_CDS with API_GLACCOUNTLINEITEM "
        "for underlying accounting document line items.\n"
        "Keep `$select` focused on key fields plus fields needed to answer the question.\n"
        "Do not use this API when the user asks for journal entry item master-data names such as "
        "company code name, cost center name, or profit center name on journal entry items.\n"
        "For wording such as \"company code and company code name for journal entry line items\", "
        "select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, and "
        "`A_JournalEntryItemBasic.CompanyCodeName`."
    )

    relevant = LlmApiRouter._relevant_skill_lines_for_prompt(
        skill_summary,
        user_input="Show company code and company code name for journal entry line items",
        max_lines=2,
    )

    assert "company code and company code name for journal entry line items" in relevant[0]
    assert all("balance drilldown" not in line for line in relevant)


def test_api_router_keeps_sales_order_delivery_skill_guidance_after_compaction() -> None:
    valid = {
        "resolved_user_input": "query delivery documents for sales order 3773",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_OUTBOUND_DELIVERY_SRV",
                "confidence": 0.92,
                "reason": "Outbound delivery exposes OrderID as a sales order reference filter.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Delivery documents for sales order",
        "business_domain": "Sales and Distribution",
        "business_object": "Outbound Delivery",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_OUTBOUND_DELIVERY_SRV",
            "short_description": "Outbound delivery API.",
            "primary_business_objects": ["Outbound Delivery"],
            "top_entities": ["A_OutbDeliveryHeader"],
            "top_filter_fields": ["A_OutbDeliveryItem.ReferenceSDDocument"],
            "top_answer_fields": ["A_OutbDeliveryHeader.DeliveryDocument"],
            "api_skill_summary": (
                "Generic outbound delivery guidance. " + ("x" * 300) + "\n"
                "- For sales order delivery document requests, query "
                "A_OutbDeliveryItem.ReferenceSDDocument directly."
            ),
        }
    ]
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询销售订单3773的交货单", catalog)

    assert decision.selected_apis[0].service_name == "API_OUTBOUND_DELIVERY_SRV"
    assert decision.requires_multi_api is False
    prompt = client.calls[0]["user_prompt"]
    assert "Relevant skill guidance" in prompt
    assert "A_OutbDeliveryItem.ReferenceSDDocument directly" in prompt


def test_api_router_keeps_material_open_sales_order_skill_guidance_after_compaction() -> None:
    valid = {
        "resolved_user_input": "query material MZ-TG-Y240 undelivered sales orders",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_SALES_ORDER_SRV",
                "confidence": 0.92,
                "reason": "Sales order item exposes material and delivery status filters.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Undelivered sales orders for material",
        "business_domain": "Sales and Distribution",
        "business_object": "Sales Order Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_SALES_ORDER_SRV",
            "short_description": "Sales order API.",
            "primary_business_objects": ["Sales Order", "Sales Order Item"],
            "top_entities": ["A_SalesOrder", "A_SalesOrderItem"],
            "top_filter_fields": [
                "A_SalesOrder.SalesOrder",
                "A_SalesOrderItem.Material",
                "A_SalesOrderItem.DeliveryStatus",
            ],
            "top_answer_fields": ["A_SalesOrder.SalesOrder", "A_SalesOrderItem.Material"],
            "api_skill_summary": (
                "Generic sales order guidance. " + ("x" * 300) + "\n"
                "- For requests such as `查询物料MZ-TG-Y240的未交货销售订单`, answer from "
                "`A_SalesOrderItem`; filter `A_SalesOrderItem.Material eq '<material>'` "
                "and `A_SalesOrderItem.DeliveryStatus ne 'C'`."
            ),
        }
    ]
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询物料MZ-TG-Y240的未交货销售订单", catalog)

    assert decision.selected_apis[0].service_name == "API_SALES_ORDER_SRV"
    prompt = client.calls[0]["user_prompt"]
    assert "Relevant skill guidance" in prompt
    assert "A_SalesOrderItem.DeliveryStatus" in prompt
    assert "ne" in prompt


def test_api_router_keeps_delivered_not_billed_delivery_skill_guidance_after_compaction() -> None:
    valid = {
        "resolved_user_input": "query customer 17100003 delivered but not billed delivery documents",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_OUTBOUND_DELIVERY_SRV",
                "confidence": 0.92,
                "reason": "Outbound delivery exposes delivery billing status directly.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Delivered but not billed outbound deliveries",
        "business_domain": "Sales and Distribution",
        "business_object": "Outbound Delivery",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_OUTBOUND_DELIVERY_SRV",
            "short_description": "Outbound delivery API.",
            "primary_business_objects": ["Outbound Delivery"],
            "top_entities": ["A_OutbDeliveryHeader"],
            "top_filter_fields": [
                "A_OutbDeliveryHeader.SoldToParty",
                "A_OutbDeliveryHeader.OverallGoodsMovementStatus",
                "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus",
            ],
            "top_answer_fields": ["A_OutbDeliveryHeader.DeliveryDocument"],
            "api_skill_summary": (
                "Generic outbound delivery guidance. " + ("x" * 300) + "\n"
                "- For delivered but not billed delivery documents, query "
                "A_OutbDeliveryHeader with OverallGoodsMovementStatus and "
                "OverallDelivReltdBillgStatus directly."
            ),
        },
        {
            "service_name": "API_BILLING_DOCUMENT_SRV",
            "short_description": "Billing document API.",
            "primary_business_objects": ["Billing Document"],
            "top_entities": ["A_BillingDocument"],
            "top_filter_fields": ["A_BillingDocument.BillingDocument"],
            "top_answer_fields": ["A_BillingDocument.BillingDocument"],
        },
    ]
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询客户17100003已发货但还没开票的交货单", catalog)

    assert decision.selected_apis[0].service_name == "API_OUTBOUND_DELIVERY_SRV"
    assert decision.requires_multi_api is False
    prompt = client.calls[0]["user_prompt"]
    assert "Relevant skill guidance" in prompt
    assert "OverallDelivReltdBillgStatus directly" in prompt


def test_api_router_compaction_keeps_user_relevant_later_entities() -> None:
    valid = {
        "resolved_user_input": "show pur ctr account records",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.8,
                "reason": "Matched a catalog entry.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Purchase contract account records",
        "business_domain": "Procurement",
        "business_object": "Purchase Contract Account",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = _catalog()
    catalog[0]["primary_business_objects"] = [
        "Purchase Contract",
        "Purchase Contract Item",
        "Purchase Contract Notes",
        "Purchase Contract Item Notes",
        "Pur Ctr Account",
    ]
    catalog[0]["top_entities"] = [
        "A_PurchaseContract",
        "A_PurchaseContractItem",
        "A_PurchaseContractNotes",
        "A_PurchaseContractItemNotes",
        "A_PurCtrAccount",
    ]
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    router.route("show pur ctr account records", catalog)

    prompt = client.calls[0]["user_prompt"]
    payload = json.loads(prompt.split("Input:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
    compact_entry = payload["api_catalog"][0]
    assert "Pur Ctr Account" in compact_entry["primary_business_objects"]
    assert "A_PurCtrAccount" in compact_entry["top_entities"]


def test_api_router_does_not_clarify_field_list_output_request() -> None:
    response = {
        "resolved_user_input": "show records with condition is deleted and condition release status",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.9,
                "reason": "Matched catalog entry.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Show status fields as output attributes.",
        "business_domain": "Procurement",
        "business_object": "Condition Supplement",
        "needs_clarification": True,
        "clarification_question": "Do you want to filter by deleted status?",
        "clarification_options": ["filter deleted", "show fields"],
    }
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route(
        "show records with condition is deleted and condition release status",
        _catalog(),
    )

    assert decision.selected_apis
    assert decision.needs_clarification is False
    assert decision.clarification_question is None
    assert decision.clarification_options == []


def test_api_router_does_not_clarify_pricing_condition_when_skill_exposes_entity() -> None:
    response = {
        "resolved_user_input": "query sales order 3773 pricing conditions",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_SALES_ORDER_SRV",
                "confidence": 0.86,
                "reason": "Sales order API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Sales order pricing conditions",
        "business_domain": "Sales and Distribution",
        "business_object": "Sales Order Pricing Condition",
        "needs_clarification": True,
        "clarification_question": "Do you mean billing document pricing conditions?",
        "clarification_options": ["sales order", "billing document"],
    }
    catalog = [
        {
            "service_name": "API_SALES_ORDER_SRV",
            "short_description": "Sales order API.",
            "primary_business_objects": ["Sales Order"],
            "top_entities": ["A_SalesOrder"],
            "top_filter_fields": ["A_SalesOrder.SalesOrder"],
            "top_answer_fields": ["A_SalesOrder.SalesOrder"],
            "api_skill_summary": (
                "For sales order pricing conditions, query "
                "A_SalesOrderItemPrElement and select ConditionType and ConditionAmount."
            ),
        }
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询销售订单3773的价格条件", catalog)

    assert decision.selected_apis[0].service_name == "API_SALES_ORDER_SRV"
    assert decision.needs_clarification is False
    assert decision.clarification_question is None
    assert decision.clarification_options == []


def test_api_router_adds_skill_declared_companion_api() -> None:
    response = {
        "resolved_user_input": "query material TG0011 purchasing info record supplier names",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_INFORECORD_PROCESS_SRV",
                "confidence": 0.9,
                "reason": "Purchasing info record selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Get supplier names for material info records.",
        "business_domain": "Purchasing",
        "business_object": "Purchasing Info Record",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_INFORECORD_PROCESS_SRV",
            "short_description": "Purchasing info record API.",
            "primary_business_objects": ["Purchasing Info Record"],
            "top_entities": ["A_PurchasingInfoRecord"],
            "top_filter_fields": ["A_PurchasingInfoRecord.Material"],
            "top_answer_fields": ["A_PurchasingInfoRecord.Supplier"],
            "api_skill_summary": (
                "Generic info record guidance.\n"
                "- For material purchasing info record supplier name requests, query "
                "API_INFORECORD_PROCESS_SRV.A_PurchasingInfoRecord by Material, then "
                "API_BUSINESS_PARTNER.A_Supplier by Supplier and select SupplierName."
            ),
        },
        {
            "service_name": "API_BUSINESS_PARTNER",
            "short_description": "Business Partner master data API.",
            "primary_business_objects": ["Supplier"],
            "top_entities": ["A_Supplier"],
            "top_filter_fields": ["A_Supplier.Supplier"],
            "top_answer_fields": ["A_Supplier.SupplierName"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询物料TG0011采购信息记录中的供应商名称", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_INFORECORD_PROCESS_SRV",
        "API_BUSINESS_PARTNER",
    ]
    assert decision.requires_multi_api is True


def test_api_router_scans_beyond_first_relevant_skill_lines_for_companion_api() -> None:
    response = {
        "resolved_user_input": "query plant 1710 production order component stock",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_MATERIAL_STOCK_SRV",
                "confidence": 0.86,
                "reason": "Stock API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Production order component stock.",
        "business_domain": "Manufacturing",
        "business_object": "Stock",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_MATERIAL_STOCK_SRV",
            "short_description": "Material stock API.",
            "primary_business_objects": ["Stock"],
            "top_entities": ["A_MatlStkInAcctMod"],
            "top_filter_fields": ["A_MatlStkInAcctMod.Plant", "A_MatlStkInAcctMod.Material"],
            "top_answer_fields": ["A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit"],
            "api_skill_summary": (
                "- Query A_MaterialStock for stock by material.\n"
                "- Query A_MatlStkInAcctMod for detailed stock quantities.\n"
                "- Filter stock by Material when provided.\n"
                "- Select stock quantity when requested.\n"
                "- Use Plant for plant stock.\n"
                "- Use StorageLocation for location stock.\n"
                "- For production order component stock requests, use "
                "API_PRODUCTION_ORDER_2_SRV together with API_MATERIAL_STOCK_SRV."
            ),
        },
        {
            "service_name": "API_PRODUCTION_ORDER_2_SRV",
            "short_description": "Production order API.",
            "primary_business_objects": ["Production Order Component"],
            "top_entities": ["A_ProductionOrderComponent_2"],
            "top_filter_fields": ["A_ProductionOrderComponent_2.Plant"],
            "top_answer_fields": ["A_ProductionOrderComponent_2.Material"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询工厂1710生产订单组件的库存", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_MATERIAL_STOCK_SRV",
        "API_PRODUCTION_ORDER_2_SRV",
    ]
    assert decision.requires_multi_api is True


def test_api_router_replaces_wrong_api_when_skill_declares_route_target() -> None:
    response = {
        "resolved_user_input": "Show company code and company code name for journal entry line items",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_GLACCOUNTLINEITEM",
                "confidence": 0.86,
                "reason": "LLM confused G/L line items with journal entry item basic records.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Journal entry item master-data names.",
        "business_domain": "Finance",
        "business_object": "Journal Entry Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_GLACCOUNTLINEITEM",
            "short_description": "G/L account line item API.",
            "primary_business_objects": ["GLAccount Line Item"],
            "top_entities": ["GLAccountLineItem"],
            "top_filter_fields": ["GLAccountLineItem.CompanyCode"],
            "top_answer_fields": ["GLAccountLineItem.CompanyCode"],
            "api_skill_summary": (
                "- Do not use this API when the user asks for journal entry item master-data names "
                "such as company code name, cost center name, or profit center name on journal entry "
                "items; route those requests to `API_JOURNALENTRYITEMBASIC_SRV`, which exposes "
                "`CompanyCodeName`, `CostCenterName`, and `ProfitCenterName`."
            ),
        },
        {
            "service_name": "API_JOURNALENTRYITEMBASIC_SRV",
            "short_description": "Journal entry item basic API.",
            "primary_business_objects": ["Journal Entry Item Basic"],
            "top_entities": ["A_JournalEntryItemBasic"],
            "top_filter_fields": ["A_JournalEntryItemBasic.CompanyCode"],
            "top_answer_fields": [
                "A_JournalEntryItemBasic.CompanyCodeName",
                "A_JournalEntryItemBasic.CostCenterName",
            ],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("Show company code and company code name for journal entry line items", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_JOURNALENTRYITEMBASIC_SRV"]
    assert decision.requires_multi_api is False


def test_api_router_ignores_negative_route_when_without_clause_excludes_request() -> None:
    response = {
        "resolved_user_input": "Show cost center names used by journal entry items",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_JOURNALENTRYITEMBASIC_SRV",
                "confidence": 0.86,
                "reason": "Journal entry item API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Journal entry cost center names.",
        "business_domain": "Finance",
        "business_object": "Journal Entry Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_JOURNALENTRYITEMBASIC_SRV",
            "short_description": "Journal entry item basic API.",
            "primary_business_objects": ["Journal Entry Item Basic"],
            "top_entities": ["A_JournalEntryItemBasic"],
            "top_filter_fields": ["A_JournalEntryItemBasic.CostCenter"],
            "top_answer_fields": ["A_JournalEntryItemBasic.CostCenterName"],
            "api_skill_summary": (
                "- For broad general ledger line item lists without master-data name requests, "
                "do not use `API_JOURNALENTRYITEMBASIC_SRV`; use `API_GLACCOUNTLINEITEM`."
            ),
        },
        {
            "service_name": "API_GLACCOUNTLINEITEM",
            "short_description": "G/L line item API.",
            "primary_business_objects": ["GLAccount Line Item"],
            "top_entities": ["GLAccountLineItem"],
            "top_filter_fields": ["GLAccountLineItem.CostCenter"],
            "top_answer_fields": ["GLAccountLineItem.CostCenter"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("Show cost center names used by journal entry items", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_JOURNALENTRYITEMBASIC_SRV"]


def test_api_router_adds_routing_work_center_companion_api_from_skill() -> None:
    response = {
        "resolved_user_input": "query product MZ-FG-R300 routing work centers",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PRODUCTION_ROUTING",
                "confidence": 0.86,
                "reason": "Production routing API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Routing work centers for a product.",
        "business_domain": "Manufacturing",
        "business_object": "Routing Work Center",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_PRODUCTION_ROUTING",
            "short_description": "Production routing API.",
            "primary_business_objects": ["Production Routing"],
            "top_entities": ["ProductionRoutingOperation"],
            "top_filter_fields": ["ProductionRoutingMatlAssgmt.Product"],
            "top_answer_fields": ["ProductionRoutingOperation.WorkCenterInternalID"],
            "api_skill_summary": (
                "- For routing work centers, use API_PRODUCTION_ROUTING together with "
                "API_WORK_CENTERS.A_WorkCenterAllCapacity by WorkCenterInternalID."
            ),
        },
        {
            "service_name": "API_WORK_CENTERS",
            "short_description": "Work center API.",
            "primary_business_objects": ["Work Center"],
            "top_entities": ["A_WorkCenterAllCapacity"],
            "top_filter_fields": ["A_WorkCenterAllCapacity.WorkCenterInternalID"],
            "top_answer_fields": ["A_WorkCenterAllCapacity.WorkCenter"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询产品MZ-FG-R300工艺路线用到的工作中心", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_PRODUCTION_ROUTING",
        "API_WORK_CENTERS",
    ]
    assert decision.requires_multi_api is True


def test_api_router_clears_resolvable_production_order_operation_clarification() -> None:
    response = {
        "resolved_user_input": "查询工厂1710工作中心上的生产订单工序",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PRODUCTION_ORDER_2_SRV",
                "confidence": 0.82,
                "reason": "Production order operations are available.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Production order operations by plant work centers.",
        "business_domain": "Manufacturing",
        "business_object": "Production Order Operation",
        "needs_clarification": True,
        "clarification_question": "Which work center?",
        "clarification_options": ["specific work center", "all work centers"],
    }
    catalog = [
        {
            "service_name": "API_PRODUCTION_ORDER_2_SRV",
            "short_description": "Production order API.",
            "primary_business_objects": ["Production Order Operation"],
            "top_entities": ["A_ProductionOrderOperation_2"],
            "top_filter_fields": ["A_ProductionOrderOperation_2.ProductionPlant"],
            "top_answer_fields": ["A_ProductionOrderOperation_2.WorkCenter"],
            "api_skill_summary": (
                'For "查询工厂1710工作中心上的生产订单工序", query '
                "A_ProductionOrderOperation_2 by ProductionPlant and select WorkCenter."
            ),
        },
        {
            "service_name": "API_PRODUCT_SRV",
            "short_description": "Product API.",
            "api_skill_summary": "",
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询工厂1710工作中心上的生产订单工序", catalog)

    assert decision.needs_clarification is False
    assert decision.clarification_question is None
    assert decision.clarification_options == []
    assert [item.service_name for item in decision.selected_apis] == ["API_PRODUCTION_ORDER_2_SRV"]


def test_api_router_does_not_add_weakly_related_companion_api_from_skill() -> None:
    response = {
        "resolved_user_input": "query plant 1710 production order operations",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PRODUCTION_ORDER_2_SRV",
                "confidence": 0.82,
                "reason": "Production order operations are available.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Production order operations.",
        "business_domain": "Manufacturing",
        "business_object": "Production Order Operation",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_PRODUCTION_ORDER_2_SRV",
            "short_description": "Production order API.",
            "primary_business_objects": ["Production Order Operation"],
            "top_entities": ["A_ProductionOrderOperation_2"],
            "top_filter_fields": ["A_ProductionOrderOperation_2.ProductionPlant"],
            "top_answer_fields": ["A_ProductionOrderOperation_2.WorkCenter"],
            "api_skill_summary": (
                "- For production order operations, query A_ProductionOrderOperation_2.\n"
                "- For production order finished product master data, use "
                "API_PRODUCTION_ORDER_2_SRV together with API_PRODUCT_SRV."
            ),
        },
        {
            "service_name": "API_PRODUCT_SRV",
            "short_description": "Product API.",
            "primary_business_objects": ["Product"],
            "top_entities": ["A_Product"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("query plant 1710 production order operations", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_PRODUCTION_ORDER_2_SRV"]
    assert decision.requires_multi_api is False


def test_api_router_adds_material_document_companion_for_production_order_documents() -> None:
    response = {
        "resolved_user_input": "query plant 1710 production order material documents",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PRODUCTION_ORDER_2_SRV",
                "confidence": 0.86,
                "reason": "Production order API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Production order material documents.",
        "business_domain": "Manufacturing",
        "business_object": "Production Order Material Document",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_PRODUCTION_ORDER_2_SRV",
            "short_description": "Production order API.",
            "primary_business_objects": ["Production Order"],
            "top_entities": ["A_ProductionOrder_2"],
            "top_filter_fields": ["A_ProductionOrder_2.ProductionPlant"],
            "top_answer_fields": ["A_ProductionOrder_2.ManufacturingOrder"],
            "api_skill_summary": (
                "- For production order material document requests, use "
                "API_PRODUCTION_ORDER_2_SRV together with API_MATERIAL_DOCUMENT_SRV."
            ),
        },
        {
            "service_name": "API_MATERIAL_DOCUMENT_SRV",
            "short_description": "Material document API.",
            "primary_business_objects": ["Material Document"],
            "top_entities": ["A_MaterialDocumentItem"],
            "top_filter_fields": ["A_MaterialDocumentItem.ManufacturingOrder"],
            "top_answer_fields": ["A_MaterialDocumentItem.MaterialDocument"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询工厂1710生产订单对应的物料凭证", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_PRODUCTION_ORDER_2_SRV",
        "API_MATERIAL_DOCUMENT_SRV",
    ]
    assert decision.requires_multi_api is True


def test_api_router_adds_product_companion_for_planned_order_material_master_data() -> None:
    response = {
        "resolved_user_input": "query plant 1710 planned order material product master data",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PLANNED_ORDERS",
                "confidence": 0.9,
                "reason": "Planned order API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Planned order material product master data.",
        "business_domain": "Manufacturing",
        "business_object": "Planned Order Material",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_PLANNED_ORDERS",
            "short_description": "Planned order API.",
            "primary_business_objects": ["Planned Order"],
            "top_entities": ["A_PlannedOrder"],
            "top_filter_fields": ["A_PlannedOrder.MRPPlant"],
            "top_answer_fields": ["A_PlannedOrder.Material"],
            "api_skill_summary": (
                "- For planned order material/product master data requests, query "
                "API_PRODUCT_SRV.A_Product by binding A_PlannedOrder.Material to A_Product.Product."
            ),
        },
        {
            "service_name": "API_PRODUCT_SRV",
            "short_description": "Product API.",
            "primary_business_objects": ["Product"],
            "top_entities": ["A_Product"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询工厂1710计划订单物料的产品主数据", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_PLANNED_ORDERS",
        "API_PRODUCT_SRV",
    ]
    assert decision.requires_multi_api is True


def test_api_router_adds_mrp_companion_for_mrp_material_stock() -> None:
    response = {
        "resolved_user_input": "query plant 1710 MRP material stock",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_MATERIAL_STOCK_SRV",
                "confidence": 0.9,
                "reason": "Stock API selected.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "MRP material stock.",
        "business_domain": "Manufacturing",
        "business_object": "MRP Material Stock",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_MATERIAL_STOCK_SRV",
            "short_description": "Material stock API.",
            "primary_business_objects": ["Stock"],
            "top_entities": ["A_MatlStkInAcctMod"],
            "top_filter_fields": ["A_MatlStkInAcctMod.Plant"],
            "top_answer_fields": ["A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit"],
            "api_skill_summary": (
                "- For MRP material stock requests, use API_MRP_MATERIALS_SRV_01 "
                "together with API_MATERIAL_STOCK_SRV."
            ),
        },
        {
            "service_name": "API_MRP_MATERIALS_SRV_01",
            "short_description": "MRP materials API.",
            "primary_business_objects": ["MRP Material"],
            "top_entities": ["A_MRPMaterial"],
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询工厂1710 MRP物料的库存", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_MATERIAL_STOCK_SRV",
        "API_MRP_MATERIALS_SRV_01",
    ]
    assert decision.requires_multi_api is True


def test_api_router_repairs_company_code_scoped_gl_clarification_to_multi_api() -> None:
    response = {
        "resolved_user_input": "查询公司1710科目表下各类总账科目",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                "confidence": 0.85,
                "reason": "The user asks for G/L accounts under a chart of accounts.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Query G/L accounts for company 1710.",
        "business_domain": "Finance",
        "business_object": "G/L Account",
        "needs_clarification": True,
        "clarification_question": "Is 1710 a chart of accounts or company code?",
        "clarification_options": ["chart of accounts", "company code"],
    }
    catalog = [
        {"service_name": "API_COMPANYCODE_SRV", "short_description": "Company code master data."},
        {
            "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
            "short_description": "G/L account in chart of accounts.",
        },
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710科目表下各类总账科目", catalog)

    assert decision.needs_clarification is False
    assert decision.requires_multi_api is True
    assert [item.service_name for item in decision.selected_apis] == [
        "API_COMPANYCODE_SRV",
        "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
    ]
    assert [item["service_name"] for item in decision.raw_response["selected_apis"]] == [
        "API_COMPANYCODE_SRV",
        "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
    ]


def test_api_router_repairs_gl_line_item_route_to_dedicated_api() -> None:
    response = {
        "resolved_user_input": "查询公司1710的总账行项目清单",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_JOURNALENTRYITEMBASIC_SRV",
                "confidence": 0.88,
                "reason": "The user asks for journal entry items.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Query G/L line items for company 1710.",
        "business_domain": "Finance",
        "business_object": "G/L Line Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710的总账行项目清单", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_GLACCOUNTLINEITEM"]
    assert decision.raw_response["selected_apis"][0]["service_name"] == "API_GLACCOUNTLINEITEM"


def test_api_router_repairs_gl_open_item_route_to_line_item_api() -> None:
    response = {
        "resolved_user_input": "查询公司1710下总账科目21100000截至2024年12月31日还没有清账的项目",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_JOURNALENTRYITEMBASIC_SRV",
                "confidence": 0.86,
                "reason": "The user asks for journal entry items by company code and G/L account.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Query open G/L account items by key date.",
        "business_domain": "Finance",
        "business_object": "G/L Open Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710下总账科目21100000截至2024年12月31日还没有清账的项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_GLACCOUNTLINEITEM"]
    assert decision.raw_response["selected_apis"][0]["service_name"] == "API_GLACCOUNTLINEITEM"


def test_api_router_repairs_open_item_balance_route_from_trial_balance() -> None:
    response = {
        "resolved_user_input": "查询科目13100000的余额，公司代码为1710，未清项目日期为今天",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "C_TRIALBALANCE_CDS",
                "confidence": 0.87,
                "reason": "The user asks for a G/L account balance.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Query G/L account open item balance by key date.",
        "business_domain": "Finance",
        "business_object": "G/L Open Item Balance",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "C_TRIALBALANCE_CDS", "short_description": "Trial balance API."},
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询科目13100000的余额，公司代码为1710，未清项目日期为今天", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_GLACCOUNTLINEITEM"]
    assert decision.raw_response["selected_apis"][0]["service_name"] == "API_GLACCOUNTLINEITEM"


def test_api_router_adds_trial_balance_companion_for_gl_balance_drilldown() -> None:
    response = {
        "resolved_user_input": "从公司1710总账科目10010000在2023年第12期的余额下钻查看凭证明细",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_GLACCOUNTLINEITEM",
                "confidence": 0.88,
                "reason": "The user asks for G/L account line item drilldown details.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Drill down from G/L account balance to accounting document line items.",
        "business_domain": "Finance",
        "business_object": "G/L Balance Drilldown",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {
            "service_name": "API_GLACCOUNTLINEITEM",
            "short_description": "G/L account line item API.",
            "api_skill_summary": (
                "For balance drilldown wording such as `余额下钻`, `从余额下钻查看凭证明细`, "
                "or `drill down from G/L account balance to line items`, use companion API "
                "`C_TRIALBALANCE_CDS` with `API_GLACCOUNTLINEITEM`."
            ),
        },
        {"service_name": "C_TRIALBALANCE_CDS", "short_description": "Trial balance API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("从公司1710总账科目10010000在2023年第12期的余额下钻查看凭证明细", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_GLACCOUNTLINEITEM",
        "C_TRIALBALANCE_CDS",
    ]
    assert decision.requires_multi_api is True


def test_api_router_repairs_gl_expense_detail_route_to_line_item_api() -> None:
    response = {
        "resolved_user_input": "查询公司1710下总账科目66000000按成本中心和利润中心归集的费用明细",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_OPLACCTGDOCITEMCUBE_SRV",
                "confidence": 0.86,
                "reason": "The user asks for operational accounting items by company code, G/L account, and cost center.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Query G/L account expense details by cost center and profit center.",
        "business_domain": "Finance",
        "business_object": "G/L Line Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_OPLACCTGDOCITEMCUBE_SRV", "short_description": "Operational accounting item cube."},
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710下总账科目66000000按成本中心和利润中心归集的费用明细", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_GLACCOUNTLINEITEM"]
    assert decision.raw_response["selected_apis"][0]["service_name"] == "API_GLACCOUNTLINEITEM"


def test_api_router_repairs_accounting_exception_route_to_operational_cube() -> None:
    response = {
        "resolved_user_input": "查询公司1710在2024年由手工凭证产生且金额超过10000的大额总账项目",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_GLACCOUNTLINEITEM",
                "confidence": 0.82,
                "reason": "The user asks for G/L items.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Query large manual accounting document items.",
        "business_domain": "Finance",
        "business_object": "Accounting Document Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
        {"service_name": "API_OPLACCTGDOCITEMCUBE_SRV", "short_description": "Operational accounting item cube."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710在2024年由手工凭证产生且金额超过10000的大额总账项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_OPLACCTGDOCITEMCUBE_SRV"]
    assert decision.raw_response["selected_apis"][0]["service_name"] == "API_OPLACCTGDOCITEMCUBE_SRV"


def test_api_router_keeps_ledger_bridge_for_leading_gl_line_items() -> None:
    response = {
        "resolved_user_input": "查询公司1710主导ledger的总账行项目",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_LEDGER_SRV", "confidence": 0.8, "reason": "Leading ledger."},
            {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "confidence": 0.8, "reason": "Line items."},
        ],
        "requires_multi_api": True,
        "intent_summary": "Query leading-ledger G/L line items.",
        "business_domain": "Finance",
        "business_object": "G/L Line Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_LEDGER_SRV", "short_description": "Ledger API."},
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710主导ledger的总账行项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_LEDGER_SRV",
        "API_GLACCOUNTLINEITEM",
    ]
    assert decision.requires_multi_api is True


def test_api_router_adds_ledger_bridge_for_leading_gl_line_items() -> None:
    response = {
        "resolved_user_input": "查询公司1710主导ledger的总账行项目",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_GLACCOUNTLINEITEM", "confidence": 0.8, "reason": "Line items."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query leading-ledger G/L line items.",
        "business_domain": "Finance",
        "business_object": "G/L Line Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_LEDGER_SRV", "short_description": "Ledger API."},
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710主导ledger的总账行项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == [
        "API_LEDGER_SRV",
        "API_GLACCOUNTLINEITEM",
    ]
    assert decision.requires_multi_api is True


def test_api_router_repairs_journal_entry_item_route_from_gl_line_item() -> None:
    response = {
        "resolved_user_input": "查询公司1710中科目10010000的日记账行项目",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_GLACCOUNTLINEITEM", "confidence": 0.8, "reason": "Line items."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query journal entry items.",
        "business_domain": "Finance",
        "business_object": "Journal Entry Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710中科目10010000的日记账行项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_JOURNALENTRYITEMBASIC_SRV"]


def test_api_router_repairs_financial_line_item_customer_route_from_gl_line_item() -> None:
    response = {
        "resolved_user_input": "查询公司1710带客户信息的财务行项目",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_GLACCOUNTLINEITEM", "confidence": 0.8, "reason": "Line items."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query financial line items with customer information.",
        "business_domain": "Finance",
        "business_object": "Financial Line Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_GLACCOUNTLINEITEM", "short_description": "G/L account line item API."},
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710带客户信息的财务行项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_JOURNALENTRYITEMBASIC_SRV"]


def test_api_router_repairs_journal_entry_item_route_from_operational_cube() -> None:
    response = {
        "resolved_user_input": "查询公司1710利润中心上的财务行项目",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_OPLACCTGDOCITEMCUBE_SRV", "confidence": 0.8, "reason": "Accounting items."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query financial line items with profit center.",
        "business_domain": "Finance",
        "business_object": "Financial Line Item",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_OPLACCTGDOCITEMCUBE_SRV", "short_description": "Operational accounting item cube."},
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710利润中心上的财务行项目", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_JOURNALENTRYITEMBASIC_SRV"]


def test_api_router_clears_bad_journal_dimension_clarification() -> None:
    response = {
        "resolved_user_input": "查询公司1710带工厂信息的财务行项目",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "confidence": 0.8, "reason": "Journal items."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query financial line items with plant information.",
        "business_domain": "Finance",
        "business_object": "Financial Line Item",
        "needs_clarification": True,
        "clarification_question": "Plant is not available on journal entry items.",
        "clarification_options": ["Use material documents instead"],
    }
    catalog = [
        {"service_name": "API_JOURNALENTRYITEMBASIC_SRV", "short_description": "Journal entry item API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710带工厂信息的财务行项目", catalog)

    assert decision.needs_clarification is False
    assert decision.clarification_question is None
    assert decision.raw_response["needs_clarification"] is False


def test_api_router_clears_cross_object_mapping_clarification() -> None:
    response = {
        "resolved_user_input": "查询公司1710成本中心对应的利润中心",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_PROFITCENTER_SRV", "confidence": 0.8, "reason": "Profit center data."},
            {"service_name": "API_COSTCENTER_SRV", "confidence": 0.7, "reason": "Cost center mapping source."},
        ],
        "requires_multi_api": True,
        "intent_summary": "Query cost center to profit center mapping.",
        "business_domain": "Controlling",
        "business_object": "Cost Center Profit Center Mapping",
        "needs_clarification": True,
        "clarification_question": "All profit centers or a specific cost center?",
        "clarification_options": ["All profit centers", "Specific cost center"],
    }
    catalog = [
        {"service_name": "API_PROFITCENTER_SRV", "short_description": "Profit center API."},
        {"service_name": "API_COSTCENTER_SRV", "short_description": "Cost center API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710成本中心对应的利润中心", catalog)

    assert decision.needs_clarification is False
    assert decision.requires_multi_api is True
    assert [item.service_name for item in decision.selected_apis] == [
        "API_PROFITCENTER_SRV",
        "API_COSTCENTER_SRV",
    ]


def test_api_router_clears_company_scoped_list_clarification() -> None:
    response = {
        "resolved_user_input": "查询公司1710成本中心的英文名称",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_COSTCENTER_SRV", "confidence": 0.8, "reason": "Cost center text data."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query cost center English names for company 1710.",
        "business_domain": "Controlling",
        "business_object": "Cost Center Text",
        "needs_clarification": True,
        "clarification_question": "Which specific cost center do you want?",
        "clarification_options": ["specific cost center", "all cost centers"],
    }
    catalog = [
        {"service_name": "API_COSTCENTER_SRV", "short_description": "Cost center API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710成本中心的英文名称", catalog)

    assert decision.needs_clarification is False
    assert decision.requires_multi_api is False
    assert [item.service_name for item in decision.selected_apis] == ["API_COSTCENTER_SRV"]


def test_api_router_repairs_cost_center_master_route_from_company_code() -> None:
    response = {
        "resolved_user_input": "查询公司1710成本中心使用的货币",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_COMPANYCODE_SRV", "confidence": 0.8, "reason": "Company code currency."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query cost center currencies for company 1710.",
        "business_domain": "Controlling",
        "business_object": "Cost Center",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    catalog = [
        {"service_name": "API_COMPANYCODE_SRV", "short_description": "Company code API."},
        {"service_name": "API_COSTCENTER_SRV", "short_description": "Cost center API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710成本中心使用的货币", catalog)

    assert [item.service_name for item in decision.selected_apis] == ["API_COSTCENTER_SRV"]


def test_api_router_clears_status_filtered_master_clarification() -> None:
    response = {
        "resolved_user_input": "查询公司1710被冻结的利润中心",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_PROFITCENTER_SRV", "confidence": 0.8, "reason": "Profit center status."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query blocked profit centers for company 1710.",
        "business_domain": "Controlling",
        "business_object": "Profit Center",
        "needs_clarification": True,
        "clarification_question": "Which technical blocked field?",
        "clarification_options": ["deletion flag", "posting block"],
    }
    catalog = [
        {"service_name": "API_PROFITCENTER_SRV", "short_description": "Profit center API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710被冻结的利润中心", catalog)

    assert decision.needs_clarification is False
    assert [item.service_name for item in decision.selected_apis] == ["API_PROFITCENTER_SRV"]


def test_api_router_clears_master_attribute_clarification() -> None:
    response = {
        "resolved_user_input": "查询公司1710成本中心的标准层级区域",
        "should_carry_context": False,
        "selected_apis": [
            {"service_name": "API_COSTCENTER_SRV", "confidence": 0.8, "reason": "Cost center master data."},
        ],
        "requires_multi_api": False,
        "intent_summary": "Query cost center standard hierarchy area.",
        "business_domain": "Controlling",
        "business_object": "Cost Center",
        "needs_clarification": True,
        "clarification_question": "Which hierarchy field?",
        "clarification_options": ["standard hierarchy", "functional area"],
    }
    catalog = [
        {"service_name": "API_COSTCENTER_SRV", "short_description": "Cost center API."},
    ]
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("查询公司1710成本中心的标准层级区域", catalog)

    assert decision.needs_clarification is False
    assert [item.service_name for item in decision.selected_apis] == ["API_COSTCENTER_SRV"]


def test_api_router_keeps_clarification_for_explicit_filter_request() -> None:
    response = {
        "resolved_user_input": "show only deleted records",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.9,
                "reason": "Matched catalog entry.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Filter by deleted status.",
        "business_domain": "Procurement",
        "business_object": "Condition Supplement",
        "needs_clarification": True,
        "clarification_question": "Which deleted status value should be used?",
        "clarification_options": ["true", "false"],
    }
    client = SequencedClient([json.dumps(response)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    decision = router.route("show only deleted records", _catalog())

    assert decision.needs_clarification is True
    assert decision.clarification_question == "Which deleted status value should be used?"


def test_api_router_compacts_recent_cases_before_prompting() -> None:
    valid = {
        "resolved_user_input": "show production routing status records",
        "should_carry_context": False,
        "selected_apis": [
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "confidence": 0.8,
                "reason": "Matched a catalog entry.",
            }
        ],
        "requires_multi_api": False,
        "intent_summary": "Status records",
        "business_domain": "Manufacturing",
        "business_object": "Production Routing Status",
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }
    huge_case = {
        "case_id": "case-large",
        "request": {"user_input": "show production routing status records"},
        "final_plan": {
            "service_name": "API_PRODUCTION_ROUTING",
            "entity_set": "ProductionRoutingStatus",
        },
        "final_status": "success",
        "response_preview": {"results": [{"payload": "x" * 100000}]},
        "schema_context_summary": {"entities": [{"fields": ["x" * 100000]}]},
        "planning_attempts": [{"raw": "x" * 100000}],
        "feedback_memories_used": [
            {
                "case_id": "memory-1",
                "lesson": "Use ProductionRoutingStatus for routing status records." + ("x" * 1000),
                "preferred_entities": ["ProductionRoutingStatus"],
            }
        ],
    }
    client = SequencedClient([json.dumps(valid)])
    router = LlmApiRouter(llm_client=client, enabled=True, allow_default_fallback=False)

    router.route(
        "show production routing status records",
        _catalog(),
        recent_cases=[huge_case],
        latest_clarification_case=huge_case,
    )

    prompt = client.calls[0]["user_prompt"]
    payload = json.loads(prompt.split("Input:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
    recent_case = payload["recent_cases"][0]
    clarification_case = payload["latest_clarification_case"]
    assert "response_preview" not in recent_case
    assert "schema_context_summary" not in recent_case
    assert "planning_attempts" not in recent_case
    assert recent_case["selected_api"] == "API_PRODUCTION_ROUTING"
    assert recent_case["entity_set"] == "ProductionRoutingStatus"
    assert len(json.dumps(payload, ensure_ascii=False)) < 10000
    assert len(clarification_case["feedback_memories_used"][0]["lesson"]) <= 260


def test_history_payload_exposes_feedback_memories_used() -> None:
    memory = {
        "case_id": "feedback-case",
        "lesson": "Use IsFinallyInvoiced=false for open invoice purchase orders.",
        "preferred_fields": ["IsFinallyInvoiced"],
    }
    api_skill = {
        "service_name": "API_PURCHASEORDER_PROCESS_SRV",
        "path": "data/api_skills/API_PURCHASEORDER_PROCESS_SRV/skill.md",
    }

    payload = _history_entry_to_payload(
        {
            "case_id": "case-1",
            "created_at": "2026-04-27T00:00:00+08:00",
            "request": {"user_input": "query open invoice purchase orders"},
            "initial_plan": {"service_name": "API_PURCHASEORDER_PROCESS_SRV", "entity_set": "A_PurchaseOrderItem"},
            "final_plan": {"service_name": "API_PURCHASEORDER_PROCESS_SRV", "entity_set": "A_PurchaseOrderItem"},
            "final_status": "failed",
            "feedback_memories_used": [memory],
            "schema_context_summary": {"api_skill": api_skill},
        }
    )

    assert payload["feedback_memories_used"] == [memory]
    assert payload["result_snapshot"]["feedback_memories_used"] == [memory]
    assert payload["api_skill_used"] == api_skill
    assert payload["result_snapshot"]["api_skill_used"] == api_skill
