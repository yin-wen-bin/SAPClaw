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
