import json

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, QueryPlan, SelectedApi
from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent
from sap_odata_agent.infrastructure.llm.schema_research_agent import LlmSchemaResearchAgent


class StubClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.system_prompt = ""
        self.user_prompt = ""

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(self.response)


def test_schema_research_agent_materializes_llm_field_analysis() -> None:
    client = StubClient(
        {
            "available": True,
            "business_intent": "Find purchase orders that are not fully received.",
            "field_reviews": [
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field": "GoodsReceiptIsExpected",
                    "meaning": "Goods receipt is expected or required.",
                    "suitable": False,
                    "reason": "It does not prove open receipt status.",
                    "risk": "Can include fully received orders.",
                },
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field": "MissingField",
                    "meaning": "Invalid field",
                    "suitable": True,
                },
            ],
            "recommended_filters": [
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field": "IsCompletelyDelivered",
                    "operator": "eq",
                    "value": "false",
                    "value_type": "Edm.Boolean",
                    "reason": "False means delivery is not completed.",
                }
            ],
            "semantic_risks": ["Do not use expected/required flags as completion status."],
            "planner_instructions": "Use the completion flag for open receipt questions.",
        }
    )
    agent = LlmSchemaResearchAgent(llm_client=client)
    schema_context = {
        "service_name": "API_PURCHASEORDER_PROCESS_SRV",
        "candidate_fields": [
            {"entity_set": "A_PurchaseOrderItem", "field_name": "GoodsReceiptIsExpected"},
            {"entity_set": "A_PurchaseOrderItem", "field_name": "IsCompletelyDelivered"},
        ],
        "entities": [],
    }

    research = agent.research(
        AgentRequest(user_input="查询供应商为17300003的未收货采购订单"),
        ApiRouteDecision(
            selected_apis=[SelectedApi(service_name="API_PURCHASEORDER_PROCESS_SRV", confidence=0.9, reason="test")]
        ),
        schema_context,
    )

    assert research["available"] is True
    assert research["recommended_filters"][0]["field"] == "IsCompletelyDelivered"
    assert [item["field"] for item in research["field_reviews"]] == ["GoodsReceiptIsExpected"]
    assert "schema_context" in client.user_prompt


def test_result_verifier_agent_blocks_unsupported_business_conclusion() -> None:
    client = StubClient(
        {
            "passed": False,
            "issues": [
                {
                    "code": "unsupported_business_conclusion",
                    "message": "The returned flag indicates expectation, not open receipt status.",
                    "blocking": True,
                }
            ],
            "repair_hints": {
                "preferred_filters": [
                    {
                        "entity_set": "A_PurchaseOrderItem",
                        "field": "IsCompletelyDelivered",
                        "operator": "eq",
                        "value": "false",
                    },
                    {
                        "entity_set": "A_PurchaseOrderItem",
                        "field": "DeliveryCompleted",
                        "operator": "eq",
                        "value": "false",
                    },
                ]
            },
        }
    )
    agent = LlmResultVerifierAgent(llm_client=client)

    result = agent.verify(
        AgentRequest(user_input="查询未收货采购订单"),
        QueryPlan(
            service_name="API_TEST",
            entity_set="A_PurchaseOrderItem",
            select_fields=["PurchaseOrder", "GoodsReceiptIsExpected"],
        ),
        {"result_count": 1, "results": [{"PurchaseOrder": "4500000469", "GoodsReceiptIsExpected": True}]},
        schema_research={"semantic_risks": ["GoodsReceiptIsExpected is not receipt completion."]},
        schema_context_summary={
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "available_fields": [
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field_name": "IsCompletelyDelivered",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                },
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field_name": "GoodsReceiptIsExpected",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                },
            ],
        },
    )

    assert result["passed"] is False
    assert result["issues"][0]["code"] == "unsupported_business_conclusion"
    assert result["repair_hints"]["preferred_filters"][0]["field"] == "IsCompletelyDelivered"
    assert [item["field"] for item in result["repair_hints"]["preferred_filters"]] == ["IsCompletelyDelivered"]
    assert "available_fields" in client.user_prompt


def test_result_verifier_agent_receives_api_skill_for_goods_receipt_combination() -> None:
    client = StubClient({"passed": True, "issues": [], "repair_hints": {}})
    agent = LlmResultVerifierAgent(llm_client=client)

    result = agent.verify(
        AgentRequest(user_input="查询供应商17300003的需要收货但未收货的订单"),
        QueryPlan(
            service_name="API_PURCHASEORDER_PROCESS_SRV",
            entity_set="A_PurchaseOrderItem",
            plan_kind="multi_step",
            select_fields=["PurchaseOrder", "GoodsReceiptIsExpected", "IsCompletelyDelivered"],
        ),
        {
            "result_count": 1,
            "results": [
                {
                    "PurchaseOrder": "4500000468",
                    "GoodsReceiptIsExpected": True,
                    "IsCompletelyDelivered": False,
                }
            ],
        },
        schema_context_summary={
            "service_name": "API_PURCHASEORDER_PROCESS_SRV",
            "api_skill": {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "summary": (
                    "For needs goods receipt but not yet received, use "
                    "GoodsReceiptIsExpected eq true and IsCompletelyDelivered eq false."
                ),
            },
            "available_fields": [
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field_name": "GoodsReceiptIsExpected",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                },
                {
                    "entity_set": "A_PurchaseOrderItem",
                    "field_name": "IsCompletelyDelivered",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                },
            ],
        },
    )

    assert result["passed"] is True
    assert "api_skill" in client.user_prompt
    assert "GoodsReceiptIsExpected eq true and IsCompletelyDelivered eq false" in client.user_prompt
    assert "do not reject it unless returned data contradicts it" in client.user_prompt
