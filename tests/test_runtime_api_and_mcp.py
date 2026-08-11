from __future__ import annotations

import importlib.util
import json
import tomllib
import urllib.request
from dataclasses import fields
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import ValidationError

from sap_odata_agent.agent_tools.runtime_client import SapClawRuntimeClient, _urllib_runtime_transport
from sap_odata_agent.agent_tools.runtime_mcp_server import SapClawRuntimeToolset
from sap_odata_agent.application.runtime_models import RuntimeOutputContract
from sap_odata_agent.api.app import create_app
from sap_odata_agent.api.app_dependencies import get_runtime_service
from sap_odata_agent.infrastructure.config.settings import Settings


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

    def execute_plan(self, plan, user_input="", conversation_id=None, resume_case_id=None):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": "case-plan"}

    def execute_get(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": "case-get"}

    def page(self, payload):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": payload.case_id}

    def case_snapshot(self, case_id):
        if case_id != "runtime-case":
            return {
                "schema_version": "1.0",
                "ok": False,
                "status": "not_found",
                "case_id": case_id,
                "error": {"code": "case_not_found", "message": "Runtime case not found."},
            }
        return {
            "schema_version": "1.0",
            "ok": True,
            "status": "success",
            "case_id": case_id,
            "result_snapshot": {
                "case_id": case_id,
                "execution_origin": "sapclaw_mcp",
                "data": {"results": [{"Supplier": "<SUPPLIER_ID>"}]},
            },
        }

    def feedback(self, **kwargs):
        return {"schema_version": "1.0", "ok": True, "status": "success", "case_id": kwargs["case_id"]}


def test_runtime_api_is_api_key_protected_and_root_health_is_public(monkeypatch) -> None:
    monkeypatch.setenv("SAPCLAW_API_KEYS", "runtime-test-key")
    app = create_app()
    app.dependency_overrides[get_runtime_service] = lambda: FakeRuntime()
    client = TestClient(app)

    missing = client.get("/api/v1/runtime/health")
    valid = client.get("/api/v1/runtime/health", headers={"X-API-Key": "runtime-test-key"})
    old_health = client.get("/health")

    assert missing.status_code == 401
    assert valid.status_code == 200
    assert valid.json()["ok"] is True
    assert old_health.status_code == 200
    assert old_health.json()["ok"] is True


def test_runtime_api_rejects_non_get_and_extra_plan_fields(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    app = create_app()
    app.dependency_overrides[get_runtime_service] = lambda: FakeRuntime()
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


def test_runtime_case_snapshot_supports_viewer_deep_link(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)

    app = create_app()
    app.dependency_overrides[get_runtime_service] = lambda: FakeRuntime()
    client = TestClient(app)

    response = client.get("/api/v1/runtime/cases/runtime-case")
    missing = client.get("/api/v1/runtime/cases/missing")

    assert response.status_code == 200
    snapshot = response.json()["result_snapshot"]
    assert snapshot["case_id"] == "runtime-case"
    assert snapshot["execution_origin"] == "sapclaw_mcp"
    assert snapshot["data"]["results"] == [{"Supplier": "<SUPPLIER_ID>"}]
    assert missing.json()["status"] == "not_found"


def test_runtime_page_uses_runtime_route(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    app = create_app()
    app.dependency_overrides[get_runtime_service] = lambda: FakeRuntime()
    client = TestClient(app)

    response = client.post("/api/v1/runtime/page", json={"case_id": "runtime-case", "skip": 50})

    assert response.status_code == 200
    assert response.json()["case_id"] == "runtime-case"


def test_legacy_http_routes_are_absent(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    app = create_app()
    app.dependency_overrides[get_runtime_service] = lambda: FakeRuntime()
    client = TestClient(app)

    assert client.post("/api/v1/agent/query", json={}).status_code == 404
    assert client.post("/api/v1/queries", json={}).status_code == 404
    assert client.get("/api/v1/queries/old-case/pages").status_code == 404


def test_legacy_mcp_llm_modules_and_settings_are_absent() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]
    setting_names = {item.name for item in fields(Settings)}

    assert "sapclaw-mcp" not in scripts
    assert set(scripts) >= {"sapclaw-runtime-mcp", "sapclaw-runtime-e2e"}
    llm_spec = importlib.util.find_spec("sap_odata_agent.infrastructure.llm")
    assert llm_spec is None or llm_spec.loader is None
    assert not list((repo_root / "src" / "sap_odata_agent" / "infrastructure" / "llm").glob("*.py"))
    assert not any("llm" in name or "profile" in name or name == "runtime_enabled" for name in setting_names)


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
        output_contract={
            "mode": "explicit",
            "display_grain": "supplier",
            "requested_fields": ["SupplierName"],
            "display_fields": ["SupplierName"],
            "support_fields": ["Supplier"],
            "reason": "The user explicitly requested only the supplier name.",
        },
    )

    assert response["ok"] is True
    call = transport.calls[0]
    assert call["headers"]["X-API-Key"] == "runtime-secret"
    assert "runtime-secret" not in call["url"]
    assert "runtime-secret" not in json.dumps(call["payload"])
    assert call["payload"]["output_contract"]["display_fields"] == ["SupplierName"]
    assert call["timeout_seconds"] == 500.0


def test_runtime_client_sends_aggregate_resume_case_id() -> None:
    transport = RecordingRuntimeTransport()
    client = SapClawRuntimeClient(
        base_url="http://127.0.0.1:8000",
        timeout_seconds=500,
        transport=transport,
    )

    response = client.execute_plan(
        plan={"service_name": "API_TEST", "entity_set": "A_Test"},
        resume_case_id="interrupted-case",
    )

    assert response["ok"] is True
    assert transport.calls[0]["payload"]["resume_case_id"] == "interrupted-case"


def test_runtime_client_bypasses_system_proxy_for_loopback(monkeypatch) -> None:
    captured_handlers: list[tuple[object, ...]] = []

    class Response:
        status = 200
        headers = {}

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    class Opener:
        def open(self, request, timeout):
            return Response()

    def build_opener(*handlers):
        captured_handlers.append(handlers)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    _urllib_runtime_transport("GET", "http://127.0.0.1:8000/health", None, 1, {})

    assert len(captured_handlers) == 1
    assert isinstance(captured_handlers[0][0], urllib.request.ProxyHandler)
    assert captured_handlers[0][0].proxies == {}


def test_runtime_mcp_module_registers_only_runtime_tool_names() -> None:
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
        "sapclaw_runtime_open_viewer",
        "sapclaw_runtime_feedback",
    }
    assert "sapclaw_query" not in tool_names
    assert server._tool_manager._tools["sapclaw_runtime_health"].annotations.readOnlyHint is True
    assert server._tool_manager._tools["sapclaw_execute_plan"].annotations.readOnlyHint is True
    assert server._tool_manager._tools["sapclaw_runtime_open_viewer"].annotations.readOnlyHint is True
    assert server._tool_manager._tools["sapclaw_runtime_open_viewer"].annotations.idempotentHint is False
    assert server._tool_manager._tools["sapclaw_runtime_feedback"].annotations.readOnlyHint is False


def test_runtime_mcp_execute_get_uses_backend_output_contract_schema() -> None:
    from sap_odata_agent.agent_tools.runtime_mcp_server import create_mcp_server

    server = create_mcp_server(base_url="http://127.0.0.1:8000", timeout_seconds=1)
    tool = server._tool_manager._tools["sapclaw_execute_get"]
    schema = tool.parameters

    assert schema["$defs"]["RuntimeOutputContract"] == RuntimeOutputContract.model_json_schema()
    assert schema["$defs"]["RuntimeOutputContract"]["additionalProperties"] is False
    assert schema["$defs"]["RuntimeOutputContract"]["required"] == ["display_fields", "reason"]


def test_runtime_mcp_execute_get_rejects_invalid_output_contract_before_execution() -> None:
    from sap_odata_agent.agent_tools.runtime_mcp_server import create_mcp_server

    server = create_mcp_server(base_url="http://127.0.0.1:8000", timeout_seconds=1)
    argument_model = server._tool_manager._tools["sapclaw_execute_get"].fn_metadata.arg_model

    try:
        argument_model.model_validate(
            {
                "service_name": "API_PURCHASEORDER_PROCESS_SRV",
                "resource_path": "A_PurchaseOrder",
                "output_contract": {
                    "required_fields": ["PurchaseOrder"],
                    "key_fields": ["PurchaseOrder"],
                },
            }
        )
    except ValidationError as exc:
        error_types = {item["type"] for item in exc.errors()}
        assert "missing" in error_types
        assert "extra_forbidden" in error_types
    else:  # pragma: no cover
        raise AssertionError("MCP accepted an output contract rejected by the backend model.")


def test_runtime_open_viewer_validates_case_and_uses_system_browser() -> None:
    class ViewerClient:
        base_url = "http://127.0.0.1:8000"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def health(self):
            self.calls.append("health")
            return {"data": {"viewer_enabled": True}}

        def case_snapshot(self, case_id):
            self.calls.append(f"case:{case_id}")
            return {"success": True}

    opened: list[str] = []
    client = ViewerClient()
    tools = SapClawRuntimeToolset(client, browser_opener=lambda url: opened.append(url) is None)

    response = tools.open_viewer("case-123", page=2)

    assert response["ok"] is True
    assert response["viewer_url"] is None
    assert response["metadata"]["opened_in_system_browser"] is True
    assert client.calls == ["health", "case:case-123"]
    assert opened == ["http://127.0.0.1:8000/?case_id=case-123&page=2"]


def test_runtime_open_viewer_rejects_non_loopback_runtime_url() -> None:
    class RemoteViewerClient:
        base_url = "https://runtime.example"

        def health(self):
            return {"data": {"viewer_enabled": True}}

        def case_snapshot(self, case_id):
            raise AssertionError("Remote case snapshot should not be requested.")

    opened: list[str] = []
    tools = SapClawRuntimeToolset(
        RemoteViewerClient(),
        browser_opener=lambda url: opened.append(url) is None,
    )

    response = tools.open_viewer("case-123")

    assert response["ok"] is False
    assert response["status"] == "viewer_unavailable"
    assert opened == []


def test_runtime_open_viewer_keeps_compact_single_result_in_codex() -> None:
    class CompactResultClient:
        base_url = "http://127.0.0.1:8000"

        def health(self):
            return {"data": {"viewer_enabled": True}}

        def case_snapshot(self, case_id):
            return {
                "result_snapshot": {
                    "success": True,
                    "data": {
                        "result_count": 1,
                        "results": [{"Answer": "value"}],
                        "pagination": {"has_next": False},
                    },
                    "presentation": {"columns": ["Answer"]},
                }
            }

    opened: list[str] = []
    tools = SapClawRuntimeToolset(
        CompactResultClient(),
        browser_opener=lambda url: opened.append(url) is None,
    )

    response = tools.open_viewer("case-123")

    assert response["ok"] is True
    assert response["status"] == "not_required"
    assert response["data"]["reason"] == "compact_single_result"
    assert response["metadata"]["opened_in_system_browser"] is False
    assert opened == []
