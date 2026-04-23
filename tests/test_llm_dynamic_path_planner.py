import json
from pathlib import Path

from sap_odata_agent.domain.models import (
    AgentRequest,
    CardinalityPolicy,
    QueryConstraints,
    QueryShape,
    RetrievedContext,
    RetrievedDocument,
)
from sap_odata_agent.infrastructure.llm.dynamic_path_planner import LlmDynamicPathPlanner


def _write_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_AddressEmailAddress", "A_BusinessPartnerAddress", "A_BusinessPartner"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_AddressEmailAddress",
                    "key_fields": ["AddressID", "OrdinalNumber"],
                    "default_select_fields": ["AddressID", "EmailAddress"],
                    "supported_methods": ["GET"],
                    "description": "Address email data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "key_fields": ["BusinessPartner", "AddressID"],
                    "default_select_fields": ["BusinessPartner", "AddressID"],
                    "supported_methods": ["GET"],
                    "description": "Business partner address data",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                    "supported_methods": ["GET"],
                    "description": "Business partner master data",
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
                    "entity_set": "A_AddressEmailAddress",
                    "field_name": "AddressID",
                    "label": "Address ID",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_AddressEmailAddress",
                    "field_name": "EmailAddress",
                    "label": "电子邮件地址",
                    "business_aliases": ["email", "mail"],
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "AddressID",
                    "label": "Address ID",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartnerAddress",
                    "field_name": "BusinessPartner",
                    "label": "业务伙伴",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartner",
                    "label": "业务伙伴",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartnerFullName",
                    "label": "名称",
                    "filterable": False,
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "entity_graph.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "from_entity_set": "A_AddressEmailAddress",
                    "to_entity_set": "A_BusinessPartnerAddress",
                    "from_field": "AddressID",
                    "to_field": "AddressID",
                    "description": "Join email address to business partner address by AddressID.",
                },
                {
                    "service_name": "API_TEST",
                    "from_entity_set": "A_BusinessPartnerAddress",
                    "to_entity_set": "A_BusinessPartner",
                    "from_field": "BusinessPartner",
                    "to_field": "BusinessPartner",
                    "description": "Join address to business partner by BusinessPartner.",
                },
            ]
        ),
        encoding="utf-8",
    )
    for name in ("relations.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / name).write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


class StubClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.user_prompt = ""

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        self.user_prompt = user_prompt
        return json.dumps(self.response)


def test_dynamic_path_planner_materializes_llm_multistep_email_to_bp(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = StubClient(
        {
            "plan_kind": "multi_step",
            "http_method": "GET",
            "target_entity_set": "A_BusinessPartner",
            "target_field": "BusinessPartner",
            "anchor_value": "info@10300006.com",
            "steps": [
                {
                    "step_id": "find_email",
                    "entity_set": "A_AddressEmailAddress",
                    "select_fields": ["AddressID", "EmailAddress"],
                    "filters": [{"field": "EmailAddress", "operator": "eq", "value": "info@10300006.com"}],
                    "top": 50,
                },
                {
                    "step_id": "resolve_bp_address",
                    "entity_set": "A_BusinessPartnerAddress",
                    "select_fields": ["BusinessPartner", "AddressID"],
                    "filter_from_previous": [
                        {"field": "AddressID", "source_step_id": "find_email", "source_field": "AddressID"}
                    ],
                    "top": 50,
                },
                {
                    "step_id": "read_bp",
                    "entity_set": "A_BusinessPartner",
                    "select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                    "filter_from_previous": [
                        {
                            "field": "BusinessPartner",
                            "source_step_id": "resolve_bp_address",
                            "source_field": "BusinessPartner",
                        }
                    ],
                    "top": 50,
                },
            ],
            "presentation": {"kind": "table", "reason": "The result may contain multiple BPs."},
            "response_directive": "Return matching business partners as a table.",
            "rationale": "Email is on address email, BP identity is reachable through address.",
        }
    )
    planner = LlmDynamicPathPlanner(index_root=tmp_path, service_name="API_TEST", llm_client=client)

    request = AgentRequest(
        user_input="查询email为info@10300006.com的BP",
        query_shape=QueryShape.SEARCH_BY_ATTRIBUTE,
        cardinality_policy=CardinalityPolicy.MANY,
        constraints=QueryConstraints(
            query_shape=QueryShape.SEARCH_BY_ATTRIBUTE,
            cardinality=CardinalityPolicy.MANY,
            target_object="business_partner",
            target_field_concepts=["BusinessPartner", "BusinessPartnerFullName"],
            filter_concepts=["EmailAddress"],
            filter_values=["info@10300006.com"],
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="field",
                title="A_AddressEmailAddress.EmailAddress",
                content="Email address",
                score=20,
                metadata={"entity_set": "A_AddressEmailAddress", "field_name": "EmailAddress"},
            )
        ]
    )

    plan = planner.plan(request, context)

    assert plan.plan_kind == "multi_step"
    assert plan.steps[0].filters[0].value == "info@10300006.com"
    assert plan.steps[-1].entity_set == "A_BusinessPartner"
    assert plan.steps[-1].filter_from_previous[0].source_step_id == "resolve_bp_address"
    assert "Presentation kind selected by LLM: table." in plan.response_directive
    assert "A_AddressEmailAddress" in client.user_prompt
    assert "AddressID" in client.user_prompt


def test_dynamic_path_planner_materializes_step_level_binding_shorthand(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = StubClient(
        {
            "plan_kind": "multi_step",
            "http_method": "GET",
            "target_entity_set": "A_BusinessPartner",
            "target_field": "BusinessPartnerFullName",
            "steps": [
                {
                    "step_id": "find_email",
                    "entity_set": "A_AddressEmailAddress",
                    "select_fields": ["AddressID", "EmailAddress"],
                    "filters": [{"field": "EmailAddress", "operator": "eq", "value": "info@10300006.com"}],
                },
                {
                    "step_id": "resolve_bp_address",
                    "entity_set": "A_BusinessPartnerAddress",
                    "select_fields": ["BusinessPartner"],
                    "binding_source_field": "AddressID",
                    "binding_target_field": "AddressID",
                },
                {
                    "step_id": "read_bp",
                    "entity_set": "A_BusinessPartner",
                    "select_fields": ["BusinessPartnerFullName"],
                    "binding_source_field": "BusinessPartner",
                    "binding_target_field": "BusinessPartner",
                },
            ],
            "presentation": {"kind": "table", "reason": "The result may contain multiple BPs."},
            "response_directive": "Return matching business partners as a table.",
            "rationale": "Use shorthand joins between steps.",
        }
    )
    planner = LlmDynamicPathPlanner(index_root=tmp_path, service_name="API_TEST", llm_client=client)

    plan = planner.plan(
        AgentRequest(user_input="query BP by email info@10300006.com"),
        RetrievedContext(),
    )

    assert plan.plan_kind == "multi_step"
    assert plan.steps[1].filter_from_previous[0].field == "AddressID"
    assert plan.steps[1].filter_from_previous[0].source_step_id == "find_email"
    assert plan.steps[1].filter_from_previous[0].source_field == "AddressID"
    assert plan.steps[2].filter_from_previous[0].field == "BusinessPartner"
    assert plan.steps[2].filter_from_previous[0].source_step_id == "resolve_bp_address"
    assert plan.steps[2].filter_from_previous[0].source_field == "BusinessPartner"


def test_dynamic_path_planner_materializes_aliased_filter_from_previous_binding(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = StubClient(
        {
            "plan_kind": "multi_step",
            "target_entity_set": "A_BusinessPartnerAddress",
            "steps": [
                {
                    "step_id": "step_1",
                    "entity_set": "A_AddressEmailAddress",
                    "select_fields": ["AddressID", "EmailAddress"],
                    "filters": [{"field": "EmailAddress", "operator": "eq", "value": "info@10300006.com"}],
                },
                {
                    "step_id": "step_2",
                    "entity_set": "A_BusinessPartnerAddress",
                    "select_fields": ["BusinessPartner"],
                    "filter_from_previous": [
                        {"source_step": "step_1", "source_field": "AddressID", "target_field": "AddressID"}
                    ],
                },
            ],
            "presentation": {"kind": "table", "reason": "The result may contain multiple BPs."},
            "response_directive": "Return matching business partners as a table.",
        }
    )
    planner = LlmDynamicPathPlanner(index_root=tmp_path, service_name="API_TEST", llm_client=client)

    plan = planner.plan(
        AgentRequest(user_input="query BP by email info@10300006.com"),
        RetrievedContext(),
    )

    assert plan.steps[1].filter_from_previous[0].field == "AddressID"
    assert plan.steps[1].filter_from_previous[0].source_step_id == "step_1"
    assert plan.steps[1].filter_from_previous[0].source_field == "AddressID"
    assert "AddressID" in plan.steps[1].select_fields


def test_dynamic_path_planner_preserves_invalid_binding_for_schema_diagnostics(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = StubClient(
        {
            "plan_kind": "multi_step",
            "target_entity_set": "A_BusinessPartner",
            "steps": [
                {
                    "step_id": "step_1",
                    "entity_set": "A_AddressEmailAddress",
                    "select_fields": ["AddressID", "EmailAddress"],
                    "filters": [{"field": "EmailAddress", "operator": "eq", "value": "info@10300006.com"}],
                },
                {
                    "step_id": "step_2",
                    "entity_set": "A_BusinessPartner",
                    "select_fields": ["BusinessPartner"],
                    "filter_from_previous": [
                        {"step_id": "step_1", "source_field": "AddressID", "target_field": "AddressID"}
                    ],
                },
            ],
        }
    )
    planner = LlmDynamicPathPlanner(index_root=tmp_path, service_name="API_TEST", llm_client=client)

    plan = planner.plan(
        AgentRequest(user_input="query BP by email info@10300006.com"),
        RetrievedContext(),
    )

    assert plan.steps[1].filter_from_previous[0].field == "AddressID"
    assert plan.steps[1].filter_from_previous[0].source_step_id == "step_1"
    assert "AddressID" not in plan.steps[1].select_fields


def test_dynamic_path_planner_does_not_fallback_when_llm_unavailable(tmp_path: Path) -> None:
    _write_index(tmp_path)
    planner = LlmDynamicPathPlanner(index_root=tmp_path, service_name="API_TEST", llm_client=None, enabled=True)

    plan = planner.plan(AgentRequest(user_input="查询email为info@10300006.com的BP"), RetrievedContext())

    assert plan.entity_set == "UNKNOWN_ENTITY"
    assert plan.planner_diagnostics["planner_winner"] == "none"
    assert plan.planner_diagnostics["llm_dynamic_path_planner"]["reason"] == "llm_unavailable"


def test_dynamic_path_planner_accepts_direct_plan_with_empty_steps(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = StubClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_BusinessPartner",
            "http_method": "GET",
            "select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
            "filters": [{"field": "BusinessPartner", "operator": "eq", "value": "1000001"}],
            "steps": [],
            "target_entity_set": "A_BusinessPartner",
            "target_fields": ["BusinessPartnerFullName"],
            "presentation": {"kind": "text", "reason": "single fact"},
            "response_directive": "Answer with basic business partner information.",
            "rationale": "A direct entity contains all fields.",
        }
    )
    planner = LlmDynamicPathPlanner(index_root=tmp_path, service_name="API_TEST", llm_client=client)

    plan = planner.plan(AgentRequest(user_input="查询业务伙伴1000001的基本信息"), RetrievedContext())

    assert plan.plan_kind == "direct"
    assert plan.entity_set == "A_BusinessPartner"
    assert plan.filters[0].field == "BusinessPartner"
    assert plan.filters[0].value == "1000001"
