import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, SelectedApi
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner


class CapturingClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.system_prompt = ""
        self.user_prompt = ""

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(self.response)


def _write_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_Test"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "entity_type": "A_TestType",
                    "key_fields": ["Document"],
                    "default_select_fields": ["Document", "IsClosed"],
                    "supported_methods": ["GET"],
                    "description": "Test document items",
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "Document",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "IsClosed",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                    "selectable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    for name in ["relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"]:
        (service_dir / name).write_text("[]", encoding="utf-8")


def test_api_specific_planner_includes_api_skill_in_prompt(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "IsClosed"],
            "filters": [{"field": "IsClosed", "operator": "eq", "value": False, "value_type": "boolean"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "response_directive": "Show open documents.",
            "rationale": "The API skill says open documents use IsClosed=false.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [{"entity_set": "A_Test", "fields": [{"field_name": "Document"}, {"field_name": "IsClosed"}]}],
        "candidate_fields": [{"entity_set": "A_Test", "field_name": "IsClosed"}],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "Open documents use IsClosed eq false.",
            "content": "## Business Semantics\n- Open documents use `A_Test.IsClosed eq false`.",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="query open documents"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.entity_set == "A_Test"
    assert plan.filters[0].field == "IsClosed"
    assert "api_skill" in client.user_prompt
    assert "Open documents use" in client.user_prompt
    assert "API skills are not schema authority" in client.system_prompt
    assert "less specific similarly named field" in client.user_prompt
