from __future__ import annotations

import json
from pathlib import Path

from sap_odata_agent.tools.run_runtime_codex_e2e import (
    baseline_retryable,
    classify_codex_failure,
    compare_case,
    isolated_runtime_mcp_config,
    inject_discovered_prompt,
    load_cases,
    parse_json_object,
    percentile,
    prepare_suite,
    provider_capacity_failure,
    runtime_entry_payload,
)


def _source_case(case_id: str, user_input: str) -> dict[str, object]:
    return {
        "id": case_id,
        "scenario": f"Scenario {case_id}",
        "user_input": user_input,
        "expected_api": "API_EXAMPLE_SRV",
        "expected_capability": {"execute": True},
        "baseline": {"steps": []},
        "comparison": {"type": "exact_keys", "keys": ["ID"]},
    }


def test_prepare_suite_creates_stable_module_ids_and_preserves_natural_language(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    case_root = tmp_path / "prepared"
    module_dir = source_root / "FI"
    module_dir.mkdir(parents=True)
    source_cases = [
        _source_case("SOURCE-1", "查询公司1710本月的总账余额"),
        _source_case("SOURCE-2", "列出今天仍未清账的供应商项目"),
    ]
    (module_dir / "cases.json").write_text(
        json.dumps(source_cases, ensure_ascii=False),
        encoding="utf-8",
    )

    prepare_suite(
        source_root=source_root,
        case_root=case_root,
        modules=("FI",),
        limit_per_module=2,
    )

    prepared = load_cases(case_root, ("FI",), set())
    assert [item["id"] for item in prepared] == ["RUNTIME-FI-001", "RUNTIME-FI-002"]
    assert [item["source_case_id"] for item in prepared] == ["SOURCE-1", "SOURCE-2"]
    assert [item["user_input"] for item in prepared] == [
        "查询公司1710本月的总账余额",
        "列出今天仍未清账的供应商项目",
    ]
    assert all(item["api"] == "FI" for item in prepared)
    assert all(item["test_surface"] == "codex_sapclaw_mcp" for item in prepared)


def test_parse_json_object_accepts_fenced_or_embedded_json() -> None:
    assert parse_json_object('```json\n{"case_id":"runtime-1"}\n```') == {"case_id": "runtime-1"}
    assert parse_json_object('result: {"case_id":"runtime-2"}') == {"case_id": "runtime-2"}
    assert parse_json_object("no json") is None


def test_classify_codex_failure_separates_external_capacity_failures() -> None:
    assert classify_codex_failure("You have hit your usage limit") == "codex_quota_limited"
    assert classify_codex_failure("429 Too Many Requests") == "codex_rate_limited"
    assert classify_codex_failure("Selected model is at capacity. Please try a different model.") == "codex_rate_limited"
    assert classify_codex_failure("MCP startup failed during handshaking") == "mcp_startup_failed"
    assert classify_codex_failure("MCP tool call was cancelled") == "mcp_tool_cancelled"
    assert classify_codex_failure("request timed out") == "codex_timeout"


def test_baseline_retryable_only_accepts_transient_transport_failures() -> None:
    assert baseline_retryable({"success": False, "error_message": "request timed out"}) is True
    assert baseline_retryable({"success": False, "error_message": "[WinError 10054] connection closed"}) is True
    assert baseline_retryable({"success": False, "status_code": 503}) is True
    assert baseline_retryable({"success": False, "status_code": 400, "error_message": "bad filter"}) is False


def test_runtime_entry_payload_uses_saved_runtime_audit_record() -> None:
    entry = {
        "final_status": "success",
        "execution_origin": "sapclaw_mcp",
        "request_kind": "structured_plan",
        "final_plan": {
            "service_name": "API_HEADER_SRV",
            "steps": [{"service_name": "API_ITEM_SRV"}],
        },
        "response_preview": {
            "result_count": 2,
            "results": [{"ID": "1"}, {"ID": "2"}],
        },
        "presentation": {"text": "Found two records."},
    }

    payload = runtime_entry_payload(entry)

    assert payload is not None
    assert payload["success"] is True
    assert payload["selected_apis"] == ["API_HEADER_SRV", "API_ITEM_SRV"]
    assert payload["results"] == [{"ID": "1"}, {"ID": "2"}]
    assert payload["result_count"] == 2
    assert payload["execution_origin"] == "sapclaw_mcp"


def test_provider_capacity_failure_only_matches_quota_and_rate_limit() -> None:
    assert provider_capacity_failure({"failed_layer": "codex_quota_limited"}) is True
    assert provider_capacity_failure({"failed_layer": "codex_rate_limited"}) is True
    assert provider_capacity_failure({"failed_layer": "mcp_startup_failed"}) is False


def test_percentile_uses_nearest_rank_for_e2e_latency() -> None:
    assert percentile([], 95) is None
    assert percentile([100, 200, 300, 400, 500], 50) == 300
    assert percentile([100, 200, 300, 400, 500], 95) == 500


def test_compare_case_records_alternate_route_without_failing_equivalent_results() -> None:
    case = {
        "expected_api": "API_BASELINE_SRV",
        "expected_capability": {"execute": True},
        "comparison": {"type": "count_only", "keys": []},
    }
    baseline = {"success": True, "final": {"result_count": 2, "keys": []}}
    codex_result = {
        "success": True,
        "runtime": {
            "execution_origin": "sapclaw_mcp",
            "success": True,
            "selected_api": "API_ALTERNATE_SRV",
            "selected_apis": ["API_ALTERNATE_SRV"],
            "results": [{"ID": "1"}, {"ID": "2"}],
            "result_count": 2,
        },
    }

    comparison = compare_case(case, baseline, codex_result, baseline_only=False)

    assert comparison["passed"] is True
    assert comparison["route_matches_baseline"] is False
    assert comparison["route_variance"] == "alternate_executable_route"


def test_isolated_runtime_config_registers_only_repo_local_sapclaw_mcp(tmp_path: Path) -> None:
    args = isolated_runtime_mcp_config(tmp_path, runtime_base_url="http://127.0.0.1:8101/")
    combined = " ".join(args)

    assert "mcp_servers.sapclaw_runtime.command" in combined
    assert "sap_odata_agent.agent_tools.runtime_mcp_server" in combined
    assert "http://127.0.0.1:8101" in combined
    assert tmp_path.name in combined
    assert "mcp_servers.sapclaw." not in combined


def test_inject_discovered_prompt_uses_read_only_baseline_values() -> None:
    case = {
        "user_input": "查询销售订单 {{SalesOrder}} 的完整O2C状态",
        "prompt_bindings": [
            {
                "placeholder": "{{SalesOrder}}",
                "source_step": "discover_order",
                "source_field": "SalesDocument",
            }
        ],
    }
    baseline = {
        "steps": [
            {"id": "discover_order", "results": [{"SalesDocument": "0000003773"}]}
        ]
    }

    resolved = inject_discovered_prompt(case, baseline)

    assert resolved["user_input"] == "查询销售订单 0000003773 的完整O2C状态"
    assert resolved["discovery_prompt_values"] == {"{{SalesOrder}}": "0000003773"}
