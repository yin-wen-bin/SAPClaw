from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sap_odata_agent.agent_tools.client import SapClawClient, SapClawClientError
from sap_odata_agent.agent_tools.mcp_server import SapClawToolset


class RecordingTransport:
    def __init__(self, responses: list[tuple[int, dict[str, str], bytes] | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], bytes]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def json_response(status_code: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    return status_code, {"content-type": "application/json"}, json.dumps(payload).encode("utf-8")


def test_sapclaw_client_health_success() -> None:
    transport = RecordingTransport([json_response(200, {"status": "ok"})])
    client = SapClawClient(base_url="http://sapclaw.local/", timeout_seconds=5, transport=transport)

    assert client.health() == {"status": "ok"}
    assert transport.calls == [
        {
            "method": "GET",
            "url": "http://sapclaw.local/health",
            "payload": None,
            "timeout_seconds": 5.0,
        }
    ]


def test_sapclaw_client_query_maps_payload() -> None:
    response = {
        "success": True,
        "case_id": "case-1",
        "final_message": "Supplier found.",
        "needs_clarification": False,
        "clarification_question": None,
        "clarification_options": [],
        "presentation": {"kind": "table", "rows": []},
        "data": {"results": []},
        "plan": {"service_name": "API_BUSINESS_PARTNER"},
        "attempts": [],
    }
    transport = RecordingTransport([json_response(200, response)])
    client = SapClawClient(base_url="http://127.0.0.1:8000", transport=transport)

    assert client.query(
        user_input="query supplier 17300003 basic information",
        conversation_id="conv-1",
        mode="read_only",
        llm_profile_id="openai-default",
    ) == response
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"] == "http://127.0.0.1:8000/api/v1/agent/query"
    assert transport.calls[0]["payload"] == {
        "user_input": "query supplier 17300003 basic information",
        "conversation_id": "conv-1",
        "mode": "read_only",
        "llm_profile_id": "openai-default",
    }


def test_sapclaw_client_http_error_is_structured() -> None:
    transport = RecordingTransport([json_response(400, {"detail": "bad profile"})])
    client = SapClawClient(transport=transport)

    with pytest.raises(SapClawClientError) as exc_info:
        client.query("query suppliers", llm_profile_id="missing")

    payload = exc_info.value.to_payload()
    assert payload["type"] == "http_error"
    assert payload["status_code"] == 400
    assert payload["detail"] == {"detail": "bad profile"}
    assert payload["url"].endswith("/api/v1/agent/query")


def test_sapclaw_toolset_returns_reachable_error_without_raising() -> None:
    transport = RecordingTransport([TimeoutError("timed out")])
    client = SapClawClient(transport=transport)
    tools = SapClawToolset(client)

    result = tools.query("query suppliers")

    assert result["success"] is False
    assert result["error"]["type"] == "timeout"
    assert "start_command" in result
    assert result["operation"] == "query"


def test_sapclaw_toolset_feedback_maps_to_client() -> None:
    transport = RecordingTransport([json_response(200, {"ok": True, "entry": {"case_id": "case-1"}})])
    client = SapClawClient(transport=transport)
    tools = SapClawToolset(client)

    assert tools.feedback(
        case_id="case-1",
        status="incorrect",
        comment="Wrong field.",
        expected_result="Use completion status.",
    ) == {"ok": True, "entry": {"case_id": "case-1"}}
    assert transport.calls[0]["url"].endswith("/api/v1/agent/feedback")
    assert transport.calls[0]["payload"] == {
        "case_id": "case-1",
        "status": "incorrect",
        "comment": "Wrong field.",
        "expected_result": "Use completion status.",
    }


def test_sapclaw_toolset_validates_required_query_text() -> None:
    client = SapClawClient(transport=RecordingTransport([]))
    tools = SapClawToolset(client)

    result = tools.query("")

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"
    assert result["final_message"] == "user_input is required."


def test_sapclaw_skill_package_metadata() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_root = repo_root / "skills" / "sapclaw-sap-odata"
    skill_md = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    openai_yaml = (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert skill_md.startswith("---\n")
    assert "name: sapclaw-sap-odata" in skill_md
    assert "description:" in skill_md
    assert "SAP OData" in skill_md
    assert "sapclaw_query" in skill_md
    assert "Do not read, print, summarize, or expose SAP credentials" in skill_md

    assert 'display_name: "SAPClaw SAP OData"' in openai_yaml
    assert 'value: "sapclaw"' in openai_yaml
    assert 'transport: "stdio"' in openai_yaml
