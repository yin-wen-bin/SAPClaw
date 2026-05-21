from sap_odata_agent.tools.run_llm_e2e_tests import (
    _baseline_final_result,
    _build_summary,
    _compare,
    _expected_api_matches,
    _is_rate_limited_result,
    _iter_step_bindings,
    _run_baseline,
    _run_frontend,
    _selected_services,
)
from sap_odata_agent.domain.models import AgentResponse, CompiledRequest, ExecutionAttempt, QueryPlan


def test_compare_fails_when_frontend_omits_required_fields() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "count_only",
            "keys": ["Document"],
            "required_fields": ["Document", "Amount"],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 1,
            "keys": [{"Document": "1"}],
            "results": [{"Document": "1", "Amount": "10"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "needs_clarification": False,
        "result_count": 1,
        "results": [{"Document": "1"}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is False
    assert result["failed_layer"] == "planner"
    assert result["missing_required_fields"] == ["Amount"]


def test_iter_step_bindings_supports_multiple_binding_shapes() -> None:
    step = {
        "bind": {"source_step": "a", "source_field": "Document", "target_field": "ReferenceDocument"},
        "bindings": [
            {"source_step": "b", "source_field": "Item", "target_field": "ReferenceItem"},
            {"source_step_id": "c", "source_field": "Group", "field": "TargetGroup"},
        ],
    }

    assert _iter_step_bindings(step) == [
        {"source_step": "a", "source_field": "Document", "target_field": "ReferenceDocument", "fanout": False},
        {"source_step": "b", "source_field": "Item", "target_field": "ReferenceItem", "fanout": False},
        {"source_step": "c", "source_field": "Group", "target_field": "TargetGroup", "fanout": False},
    ]


def test_compare_key_subset_passes_when_baseline_and_frontend_are_empty() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "key_subset",
            "keys": ["Document"],
            "required_fields": ["Document"],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 0,
            "keys": [],
            "results": [],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "needs_clarification": False,
        "result_count": 0,
        "results": [],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
    assert result["failed_layer"] is None


def test_baseline_final_result_applies_aggregate_transform() -> None:
    case = {
        "expected_api": "API_TEST",
        "baseline": {
            "result_transform": {
                "type": "aggregate",
                "group_by": ["CostCenter", "ProfitCenter"],
                "sum_fields": ["Amount"],
            }
        },
        "comparison": {"keys": ["CostCenter", "ProfitCenter", "Amount"]},
    }
    final_step = {
        "result_count": 3,
        "returned_count": 3,
        "key_fields": ["Document"],
        "keys": [{"Document": "1"}, {"Document": "2"}, {"Document": "3"}],
        "results": [
            {"CostCenter": "C1", "ProfitCenter": "P1", "Amount": "10.00"},
            {"CostCenter": "C1", "ProfitCenter": "P1", "Amount": "2.50"},
            {"CostCenter": "C2", "ProfitCenter": "P2", "Amount": "3"},
        ],
    }

    result = _baseline_final_result(case, final_step)

    assert result["result_count"] == 2
    assert result["keys"] == [
        {"CostCenter": "C1", "ProfitCenter": "P1", "Amount": "12.5"},
        {"CostCenter": "C2", "ProfitCenter": "P2", "Amount": "3"},
    ]


def test_run_baseline_skips_bound_step_when_source_has_no_values(tmp_path, monkeypatch) -> None:
    import sap_odata_agent.tools.run_llm_e2e_tests as runner_module

    class FakeExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
            self.calls += 1
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=True,
                status_code=200,
                response_preview={"result_count": 0, "returned_count": 0, "results": [], "_all_results": []},
            )

    class FakeSettings:
        sap_base_url = "http://sap.example"

    executor = FakeExecutor()
    monkeypatch.setattr(runner_module, "get_sap_executor", lambda: executor)
    monkeypatch.setattr(runner_module, "get_settings", lambda: FakeSettings())
    case = {
        "id": "CASE-001",
        "api": "FICO",
        "baseline": {
            "steps": [
                {
                    "id": "headers",
                    "url": "/sap/opu/odata/sap/API_TEST/Header?$select=Document&$top=5",
                    "key_fields": ["Document"],
                },
                {
                    "id": "items",
                    "url": "/sap/opu/odata/sap/API_TEST/Item?$select=Document,Item&$top=5",
                    "key_fields": ["Document", "Item"],
                    "bindings": [
                        {"source_step": "headers", "source_field": "Document", "target_field": "Document"}
                    ],
                },
            ]
        },
    }

    baseline = _run_baseline(case, tmp_path)

    assert executor.calls == 1
    assert baseline["success"] is True
    assert baseline["steps"][1]["skipped"] is True
    assert baseline["final"]["result_count"] == 0


def test_rate_limit_result_detection() -> None:
    result = {
        "comparison": {
            "reason": "Planner did not produce an executable schema plan: HTTP Error 429: Too Many Requests"
        }
    }

    assert _is_rate_limited_result(result) is True


def test_expected_apis_allow_single_relevant_api_by_default() -> None:
    case = {"expected_apis": ["API_A", "API_B"]}
    frontend = {"selected_api": "API_B", "selected_apis": ["API_B"]}

    assert _expected_api_matches(case, frontend) is True


def test_expected_apis_can_require_all_services() -> None:
    case = {"expected_apis": ["API_A", "API_B"], "require_all_expected_apis": True}
    frontend = {"selected_api": "API_B", "selected_apis": ["API_B"]}

    assert _expected_api_matches(case, frontend) is False


def test_selected_services_includes_planner_diagnostic_schema_context() -> None:
    class Plan:
        service_name = "C_TRIALBALANCE_CDS"
        steps = []
        planner_diagnostics = {
            "llm_dynamic_path_planner": {
                "schema_context": {
                    "service_names": ["C_TRIALBALANCE_CDS", "API_GLACCOUNTLINEITEM"]
                }
            }
        }

    class Response:
        plan = Plan()

    assert _selected_services(Response()) == ["C_TRIALBALANCE_CDS", "API_GLACCOUNTLINEITEM"]


def test_key_subset_allows_count_match_when_baseline_page_is_smaller() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "key_subset",
            "keys": ["Document"],
            "required_fields": ["Document"],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 3,
            "returned_count": 1,
            "keys": [{"Document": "1"}],
            "results": [{"Document": "1"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "selected_apis": ["API_TEST"],
        "needs_clarification": False,
        "result_count": 3,
        "results": [{"Document": "1"}, {"Document": "2"}, {"Document": "3"}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
    assert result["key_check_limited_by_baseline_page"] is True


def test_key_subset_allows_frontend_superset_when_upstream_baseline_step_is_limited() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "key_subset",
            "keys": ["Document", "Item"],
            "required_fields": ["Document", "Item"],
        },
    }
    baseline = {
        "success": True,
        "steps": [
            {
                "id": "headers",
                "result_count": 100,
                "returned_count": 20,
                "keys": [{"Document": "1"}],
                "results": [{"Document": "1"}],
            },
            {
                "id": "items",
                "result_count": 1,
                "returned_count": 1,
                "keys": [{"Document": "1", "Item": "10"}],
                "results": [{"Document": "1", "Item": "10"}],
            },
        ],
        "final": {
            "result_count": 1,
            "returned_count": 1,
            "keys": [{"Document": "1", "Item": "10"}],
            "results": [{"Document": "1", "Item": "10"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "selected_apis": ["API_TEST"],
        "needs_clarification": False,
        "result_count": 2,
        "results": [{"Document": "1", "Item": "10"}, {"Document": "2", "Item": "10"}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
    assert result["key_check_limited_by_baseline_page"] is True


def test_compare_accepts_required_any_field_group() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "count_only",
            "keys": ["Document"],
            "required_fields": ["Document"],
            "required_any_fields": [["GLAccountType", "IsBalanceSheetAccount", "ProfitLossAccountType"]],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 1,
            "keys": [{"Document": "1"}],
            "results": [{"Document": "1", "GLAccountType": "X"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "selected_apis": ["API_TEST"],
        "needs_clarification": False,
        "result_count": 1,
        "results": [{"Document": "1", "IsBalanceSheetAccount": True}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True


def test_run_frontend_uses_requested_llm_profile(monkeypatch) -> None:
    import sap_odata_agent.tools.run_llm_e2e_tests as runner_module

    class FakeProfile:
        id = "kimi-default"
        enabled = True

        def public_payload(self) -> dict:
            return {
                "id": self.id,
                "label": "KIMI",
                "provider": "kimi",
                "model": "kimi-for-coding",
                "protocol": "anthropic_messages",
                "enabled": True,
            }

    orchestrator_profile_ids = []
    requests = []

    class FakeOrchestrator:
        def run(self, request):
            requests.append(request)
            return AgentResponse(
                success=True,
                plan=QueryPlan(service_name="API_TEST", entity_set="A_Test"),
                validation_issues=[],
                attempts=[],
                data={"result_count": 0, "returned_count": 0, "results": []},
                case_id="case-1",
            )

    monkeypatch.setattr(runner_module, "get_llm_profile", lambda profile_id: FakeProfile())
    monkeypatch.setattr(
        runner_module,
        "get_orchestrator_for_profile",
        lambda profile_id: orchestrator_profile_ids.append(profile_id) or FakeOrchestrator(),
    )

    result = _run_frontend(
        {"id": "CASE-001", "user_input": "query something"},
        "run-1",
        llm_profile_id="kimi-default",
    )

    assert orchestrator_profile_ids == ["kimi-default"]
    assert requests[0].llm_profile_id == "kimi-default"
    assert result["llm_profile_id"] == "kimi-default"
    assert result["llm_profile"]["provider"] == "kimi"
    assert result["llm_profile"]["model"] == "kimi-for-coding"


def test_build_summary_records_llm_profile() -> None:
    summary = _build_summary(
        "run-1",
        [
            {
                "case_id": "CASE-001",
                "api": "API_TEST",
                "scenario": "basic query",
                "status": "passed",
                "failed_layer": None,
            }
        ],
        llm_profile={
            "id": "kimi-default",
            "label": "KIMI",
            "provider": "kimi",
            "model": "kimi-for-coding",
            "protocol": "anthropic_messages",
            "enabled": True,
        },
    )

    assert summary["llm_profile"]["id"] == "kimi-default"
    assert summary["llm_profile"]["model"] == "kimi-for-coding"
