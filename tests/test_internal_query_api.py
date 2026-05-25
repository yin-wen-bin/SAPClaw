from __future__ import annotations

from fastapi.testclient import TestClient

from sap_odata_agent.api.app import create_app
from sap_odata_agent.api.routes import queries as queries_module
from sap_odata_agent.domain.models import (
    AgentResponse,
    CompiledRequest,
    ExecutionAttempt,
    ExecutionMode,
    QueryPlan,
    ResultPresentation,
)


class FakeProfile:
    id = "fake-profile"
    enabled = False


class FakeOrchestrator:
    def __init__(self, response: AgentResponse) -> None:
        self.response = response
        self.last_request = None

    def run(self, request):
        self.last_request = request
        return self.response


def _success_response() -> AgentResponse:
    return AgentResponse(
        success=True,
        plan=QueryPlan(
            service_name="API_BUSINESS_PARTNER",
            entity_set="A_Supplier",
            http_method="GET",
            select_fields=["Supplier"],
            top=1,
        ),
        validation_issues=[],
        attempts=[],
        data={
            "result_count": 1,
            "results": [
                {
                    "Supplier": "17300003",
                    "__metadata": {"uri": "https://sap.example/internal"},
                }
            ],
            "pagination": {"page_size": 50, "skip": 0, "has_next": False},
        },
        presentation=ResultPresentation(
            kind="table",
            title="Suppliers",
            text="Loaded 1 row.",
            columns=["Supplier"],
            rows=[{"Supplier": "17300003"}],
        ),
        final_message="Query executed successfully.",
        case_id="case-1",
        total_duration_ms=12.3,
    )


def _patch_query_runtime(monkeypatch, response: AgentResponse) -> FakeOrchestrator:
    orchestrator = FakeOrchestrator(response)
    monkeypatch.setattr(queries_module, "get_llm_profile", lambda profile_id=None: FakeProfile())
    monkeypatch.setattr(queries_module, "get_orchestrator_for_profile", lambda profile_id=None: orchestrator)
    return orchestrator


def test_internal_query_allows_requests_without_api_key_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    orchestrator = _patch_query_runtime(monkeypatch, _success_response())
    client = TestClient(create_app())

    response = client.post("/api/v1/queries", json={"input": "query supplier 17300003"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "case-1"
    assert payload["status"] == "success"
    assert payload["data"]["columns"] == ["Supplier"]
    assert payload["data"]["rows"] == [{"Supplier": "17300003"}]
    assert payload["metadata"] == {
        "service_name": "API_BUSINESS_PARTNER",
        "entity_set": "A_Supplier",
    }
    assert payload["duration_ms"] == 12.3
    assert payload["error"] is None
    assert "plan" not in payload
    assert "attempts" not in payload
    assert "final_query_url" not in payload
    assert "__metadata" not in str(payload)
    assert orchestrator.last_request.mode == ExecutionMode.READ_ONLY


def test_internal_query_requires_api_key_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("SAPCLAW_API_KEYS", "test-api-key,backup-test-api-key")
    _patch_query_runtime(monkeypatch, _success_response())
    client = TestClient(create_app())

    missing_key = client.post("/api/v1/queries", json={"input": "query supplier"})
    wrong_key = client.post("/api/v1/queries", json={"input": "query supplier"}, headers={"X-API-Key": "wrong"})
    valid_key = client.post(
        "/api/v1/queries",
        json={"input": "query supplier"},
        headers={"X-API-Key": "test-api-key"},
    )

    assert missing_key.status_code == 401
    assert wrong_key.status_code == 401
    assert valid_key.status_code == 200


def test_health_is_not_protected_by_internal_api_key(monkeypatch) -> None:
    monkeypatch.setenv("SAPCLAW_API_KEYS", "test-api-key")
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_internal_query_rejects_caller_supplied_mode(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    _patch_query_runtime(monkeypatch, _success_response())
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/queries",
        json={"input": "delete supplier 17300003", "mode": "write_confirm_required"},
    )

    assert response.status_code == 422


def test_internal_query_maps_non_get_plan_to_unsupported_operation(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)
    write_response = AgentResponse(
        success=False,
        plan=QueryPlan(
            service_name="API_BUSINESS_PARTNER",
            entity_set="A_Supplier",
            http_method="PATCH",
            requires_confirmation=True,
        ),
        validation_issues=[],
        attempts=[],
        data=None,
        presentation=None,
        final_message="Write operation is not supported.",
        case_id="case-write",
        total_duration_ms=5.0,
    )
    orchestrator = _patch_query_runtime(monkeypatch, write_response)
    client = TestClient(create_app())

    response = client.post("/api/v1/queries", json={"input": "update supplier 17300003"})

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "unsupported_operation"
    assert "plan" not in payload
    assert "attempts" not in payload
    assert orchestrator.last_request.mode == ExecutionMode.READ_ONLY


def test_internal_query_page_returns_stable_business_payload(monkeypatch) -> None:
    monkeypatch.delenv("SAPCLAW_API_KEYS", raising=False)

    class FakeRepository:
        def get_by_case_id(self, case_id: str):
            assert case_id == "case-1"
            return {
                "case_id": "case-1",
                "final_query_url": "https://sap.example/sap/opu/odata/sap/API_TEST/A_Test?$top=20&$skip=0",
                "response_preview": {"pagination": {"page_size": 20}},
                "final_plan": {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "http_method": "GET",
                    "top": 20,
                },
                "presentation": {"title": "Tests", "columns": ["ID", "Name"]},
            }

    class FakeSapExecutor:
        def __init__(self) -> None:
            self.last_request = None

        def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
            self.last_request = compiled_request
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=True,
                status_code=200,
                response_preview={
                    "result_count": 25,
                    "results": [
                        {
                            "ID": "21",
                            "Name": "Next",
                            "__metadata": {"uri": "hidden"},
                        }
                    ],
                    "pagination": {"page_size": 20, "skip": 20, "has_next": False},
                },
            )

    executor = FakeSapExecutor()
    app = create_app()
    app.dependency_overrides[queries_module.get_case_repository] = lambda: FakeRepository()
    app.dependency_overrides[queries_module.get_sap_executor] = lambda: executor
    client = TestClient(app)

    response = client.get("/api/v1/queries/case-1/pages?skip=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "case-1"
    assert payload["status"] == "success"
    assert payload["data"]["columns"] == ["ID", "Name"]
    assert payload["data"]["rows"] == [{"ID": "21", "Name": "Next"}]
    assert payload["metadata"] == {"service_name": "API_TEST", "entity_set": "A_Test"}
    assert "$skip=20" in executor.last_request.url
    assert "$top=20" in executor.last_request.url
    assert "attempts" not in payload
    assert "final_query_url" not in payload
    assert "__metadata" not in str(payload)
