from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from sap_odata_agent.agent_tools.runtime_client import SapClawRuntimeClient
from sap_odata_agent.api.app import create_app
from sap_odata_agent.api.app_dependencies import get_case_repository, get_sap_executor, get_thin_runtime_service
from sap_odata_agent.domain.models import ExecutionAttempt


class FakeRuntime:
    def health(self):
        return {"schema_version": "1.0", "ok": True, "status": "success"}

    def catalog(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "data": payload.model_dump()}

    def schema(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "data": payload.model_dump()}

    def guidance(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "data": payload.model_dump()}

    def validate_plan(self, plan, user_input=""):
        return {"schema_version": "1.0", "ok": True, "status": "success", "data": plan.model_dump()}

    def execute_plan(self, plan, user_input="", conversation_id=None):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": "case-plan"}

    def execute_get(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": "case-get"}

    def page(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": payload.case_id}

    def feedback(self, **kwargs):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": kwargs["case_id"]}


def test_runtime_api_is_parallel_and_api_key_protected(monkeypatch) -> None:
    monkeypatch.setenv("SAPCLAW_API_KEYS", "runtime-test-key")
    app = create_app()
    app.dependency_overrides[get_thin_runtime_service] = lambda: FakeRuntime()
    client = TestClient(app)

    missing = client.get("/api/v1/runtime/health")
    valid = client.get("/api/v1/runtime/health", headers={"X-API-Key": "runtime-test-key"})
    old_health = client.get("/health")

    assert missing.status_code == 401
    assert valid.status_code == 200
    assert valid.json()["ok"] is True
    assert old_health.status_code == 200
    assert old_health.json() == {"status": "ok"}


def test_runtime_api_rejects_non_get_and_extra_plan_fields(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    app = create_app()
    app.dependency_overrides[get_thin_runtime_service] = lambda: FakeRuntime()
    client = TestClient(app)

    non_get = client.post(
        "/api/v1/runtime/validate-plan",
        json={"plan": {"service_name": "API_TEST", "entity_set": "A_Test", "http_method": "POST"}},
    )
    extra = client.post(
        "/api/v1/runtime/validate-plan",
        json={"plan": {"service_name": "API_TEST", "entity_set": "A_Test", "fallback": True}},
    )

    assert non_get.status_code == 422
    assert extra.status_code == 422


def test_agent_case_snapshot_supports_thin_viewer_deep_link(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)

    class Repository:
        def get_by_case_id(self, case_id):
            if case_id != "thin-case":
                return None
            return {
                "case_id": case_id,
                "created_at": "2026-07-10T10:00:00+08:00",
                "request": {"user_input": "query suppliers", "mode": "read_only"},
                "final_status": "success",
                "initial_plan": {
                    "service_name": "API_BUSINESS_PARTNER",
                    "entity_set": "A_Supplier",
                    "http_method": "GET",
                },
                "final_plan": {
                    "service_name": "API_BUSINESS_PARTNER",
                    "entity_set": "A_Supplier",
                    "http_method": "GET",
                },
                "response_preview": {
                    "result_count": 1,
                    "results": [{"Supplier": "<SUPPLIER_ID>"}],
                    "pagination": {"page_size": 50, "skip": 0, "has_next": False},
                },
                "presentation": {
                    "kind": "table",
                    "title": "Query results",
                    "text": "1 row",
                    "columns": ["Supplier"],
                    "rows": [{"Supplier": "<SUPPLIER_ID>"}],
                },
                "attempts": [],
                "execution_origin": "thin_mcp",
                "request_kind": "structured_plan",
            }

    app = create_app()
    app.dependency_overrides[get_case_repository] = lambda: Repository()
    client = TestClient(app)

    response = client.get("/api/v1/agent/cases/thin-case")
    missing = client.get("/api/v1/agent/cases/missing")

    assert response.status_code == 200
    snapshot = response.json()["result_snapshot"]
    assert snapshot["case_id"] == "thin-case"
    assert snapshot["execution_origin"] == "thin_mcp"
    assert snapshot["request_kind"] == "structured_plan"
    assert missing.status_code == 404


def test_agent_page_honors_thin_business_top_and_removes_skiptoken(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)

    class Repository:
        def get_by_case_id(self, case_id):
            return {
                "case_id": case_id,
                "execution_origin": "thin_mcp",
                "runtime_request": {
                    "pagination": {"page_size": 50, "business_top": 60, "initial_skip": 0}
                },
                "final_query_url": (
                    "https://sap.example/A_Supplier?$top=50&$skip=0&$skiptoken=opaque"
                ),
                "response_preview": {"result_count": 82, "results": []},
                "final_plan": {"service_name": "API_TEST", "entity_set": "A_Supplier"},
                "request": {"user_input": "query suppliers"},
            }

    class Executor:
        def __init__(self):
            self.requests = []

        def execute(self, request, attempt_number):
            self.requests.append(request)
            rows = [{"Supplier": str(index)} for index in range(10)]
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=request,
                success=True,
                status_code=200,
                response_preview={"result_count": 82, "results": rows},
            )

    executor = Executor()
    app = create_app()
    app.dependency_overrides[get_case_repository] = lambda: Repository()
    app.dependency_overrides[get_sap_executor] = lambda: executor
    client = TestClient(app)

    second_page = client.post("/api/v1/agent/page", json={"case_id": "thin-case", "skip": 50})
    out_of_range = client.post("/api/v1/agent/page", json={"case_id": "thin-case", "skip": 100})

    assert second_page.status_code == 200
    assert second_page.json()["data"]["result_count"] == 60
    assert second_page.json()["data"]["pagination"]["has_next"] is False
    assert "$top=10" in executor.requests[0].url
    assert "$skip=50" in executor.requests[0].url
    assert "$skiptoken" not in executor.requests[0].url
    assert out_of_range.status_code == 416
    assert len(executor.requests) == 1


class RecordingRuntimeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method, url, payload, timeout_seconds, headers):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "headers": headers,
            }
        )
        body = json.dumps({"schema_version": "1.0", "ok": True, "status": "success"}).encode("utf-8")
        return 200, {"content-type": "application/json"}, body


def test_runtime_client_sends_api_key_in_header_only() -> None:
    transport = RecordingRuntimeTransport()
    client = SapClawRuntimeClient(
        base_url="http://127.0.0.1:8000",
        timeout_seconds=500,
        api_key="runtime-secret",
        transport=transport,
    )

    response = client.execute_get(
        service_name="API_BUSINESS_PARTNER",
        resource_path="A_Supplier",
        query_options={"$select": "Supplier"},
    )

    assert response["ok"] is True
    call = transport.calls[0]
    assert call["headers"]["X-API-Key"] == "runtime-secret"
    assert "runtime-secret" not in call["url"]
    assert "runtime-secret" not in json.dumps(call["payload"])
    assert call["timeout_seconds"] == 500.0


def test_runtime_mcp_module_registers_only_thin_tool_names() -> None:
    from sap_odata_agent.agent_tools.runtime_mcp_server import create_mcp_server

    server = create_mcp_server(base_url="http://127.0.0.1:8000", timeout_seconds=1)
    tool_names = set(server._tool_manager._tools)

    assert tool_names == {
        "sapclaw_runtime_health",
        "sapclaw_catalog",
        "sapclaw_schema",
        "sapclaw_guidance",
        "sapclaw_validate_plan",
        "sapclaw_execute_plan",
        "sapclaw_execute_get",
        "sapclaw_runtime_page",
        "sapclaw_runtime_feedback",
    }
    assert "sapclaw_query" not in tool_names
    assert server._tool_manager._tools["sapclaw_runtime_health"].annotations.readOnlyHint is True
    assert server._tool_manager._tools["sapclaw_execute_plan"].annotations.readOnlyHint is True
    assert server._tool_manager._tools["sapclaw_runtime_feedback"].annotations.readOnlyHint is False
