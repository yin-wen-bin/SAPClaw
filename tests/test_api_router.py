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
        }
    ]


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
